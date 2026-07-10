#!/usr/bin/env bash
# orchestrate.sh — headless Codex execution leg of the dual-brain loop.
#
# Automates steps 2–4: critique -> branch -> implement -> open PR. It then
# records a handoff and stops. Steps 5–7 run in a Claude session.
#
# Usage: scripts/orchestrate.sh [--resume] [--timeout SECONDS] <topic> [path/to/PLAN.md]
#
# Env:
#   ORCH_SANDBOX      Codex sandbox for implementation (default workspace-write)
#   ORCH_EXEC_EFFORT  low|medium|high|xhigh (default medium)
#   ORCH_WORKTREE=1   create a dedicated worktree off origin/<default-branch>
#   ORCH_STALL_KILL   seconds without Codex output before retry (default 300)
#   ORCH_MAX_RETRY    retry count after a hung step (default 2)
#   ORCH_TITLE        dashboard card title (default topic)
#   ORCH_GATE_TIMEOUT seconds to wait for a gate; 0 waits forever (default 0)
#   ORCH_VERIFY_TIMEOUT seconds allowed per configured verify command (default 900)
#   ORCH_DRYRUN=1     print the command plan without writes, auth, fetch, or emit
set -Eeuo pipefail

die() { echo "orchestrate: $*" >&2; exit 1; }

RESUME=0
GATE_TIMEOUT="${ORCH_GATE_TIMEOUT:-0}"
while [[ "${1:-}" == --* ]]; do
  case "$1" in
    --resume) RESUME=1; shift ;;
    --timeout)
      [[ "${2:-}" =~ ^[0-9]+$ ]] || die "--timeout requires a non-negative integer"
      GATE_TIMEOUT="$2"; shift 2 ;;
    --) shift; break ;;
    *) die "unknown option: $1" ;;
  esac
done

TOPIC="${1:-}"
[[ -n "$TOPIC" ]] || die "usage: orchestrate.sh [--resume] [--timeout SECONDS] <topic> [PLAN.md]"
[[ "$TOPIC" =~ ^[a-z0-9][a-z0-9._-]{0,60}$ ]] || \
  die "invalid topic '$TOPIC' (use 1-61 lowercase letters, digits, dot, underscore, or hyphen)"

PLAN="${2:-PLAN-${TOPIC}.md}"
BRANCH="orch/${TOPIC}"
SANDBOX="${ORCH_SANDBOX:-workspace-write}"
EXEC_EFFORT="${ORCH_EXEC_EFFORT:-medium}"
WORKTREE="${ORCH_WORKTREE:-0}"
DRY="${ORCH_DRYRUN:-0}"
RESTART="${ORCH_RESTART:-0}"
DEDICATED_WORKTREE="${ORCH_DEDICATED_WORKTREE:-$WORKTREE}"
VERIFY_TIMEOUT="${ORCH_VERIFY_TIMEOUT:-900}"

case "$EXEC_EFFORT" in low|medium|high|xhigh|ultra) ;; *)
  die "ORCH_EXEC_EFFORT must be one of: low, medium, high, xhigh, ultra" ;;
esac
[[ "$VERIFY_TIMEOUT" =~ ^[1-9][0-9]*$ ]] || die "ORCH_VERIFY_TIMEOUT must be a positive integer"
git check-ref-format --branch "$BRANCH" >/dev/null 2>&1 || die "invalid branch name: $BRANCH"
git rev-parse --show-toplevel >/dev/null 2>&1 || die "not in a git repo"
[[ -f "$PLAN" ]] || die "plan file not found: $PLAN"

PLAN_ABS="$(cd "$(dirname "$PLAN")" && pwd)/$(basename "$PLAN")"
ORIG_ROOT="$(git rev-parse --show-toplevel)"
SELF="$(cd "$(dirname "$0")" && pwd)/$(basename "$0")"
VERIFY_HELPER="$(dirname "$SELF")/orchestrate_verify.py"
[[ -f "$VERIFY_HELPER" ]] || die "verify helper not found: $VERIFY_HELPER"
VERIFY_PYTHON="${ORCH_PYTHON:-}"
if [[ -n "$VERIFY_PYTHON" ]]; then
  command -v "$VERIFY_PYTHON" >/dev/null 2>&1 || die "ORCH_PYTHON not found: $VERIFY_PYTHON"
else
  for candidate in python3 python3.14 python3.13 python3.12 python3.11; do
    candidate_path="$(command -v "$candidate" 2>/dev/null || true)"
    [[ -n "$candidate_path" ]] || continue
    if "$candidate_path" -c 'import importlib.util; assert importlib.util.find_spec("tomllib") or importlib.util.find_spec("tomli")' >/dev/null 2>&1; then
      VERIFY_PYTHON="$candidate_path"
      break
    fi
  done
fi
[[ -n "$VERIFY_PYTHON" ]] || die "verify gate requires Python 3.11+ with tomllib (or Python with tomli)"
SELF_REL=""
[[ "$SELF" == "$ORIG_ROOT/"* ]] && SELF_REL="${SELF#"$ORIG_ROOT/"}"
REPO_NAME="${ORCH_REPO_NAME:-$(basename "$ORIG_ROOT")}"
BATON_ROOT="${ORCH_BATON_ROOT:-$ORIG_ROOT}"
RUN_ID="${ORCH_RUN_ID:-$REPO_NAME-$TOPIC}"
CONFIG_ROOT="$ORIG_ROOT"
VERIFY_CONFIG="$CONFIG_ROOT/.ai/orchestrate.toml"

if [[ "$RESUME" == "1" && -z "${ORCH_RUN_ID:-}" ]]; then
  resolved_id="$(python3 - "$HOME/.orchestrate/runs" "$TOPIC" "$(pwd -P)" <<'PY'
import glob, json, os, sys
matches = []
for candidate in glob.glob(os.path.join(sys.argv[1], "*.json")):
    try:
        with open(candidate) as fh:
            run = json.load(fh)
    except Exception:
        continue
    if run.get("topic") == sys.argv[2] and run.get("cwd") == sys.argv[3]:
        matches.append(run.get("id", ""))
if len(matches) == 1:
    print(matches[0])
PY
  )"
  [[ -n "$resolved_id" ]] || die "could not resolve one resumable '$TOPIC' run for $(pwd -P); run from its recorded cwd or set ORCH_RUN_ID"
  RUN_ID="$resolved_id"
fi
[[ "$RUN_ID" != */* && "$RUN_ID" != *\\* && "$RUN_ID" != "." && "$RUN_ID" != ".." && \
   "$RUN_ID" != *$'\n'* && "$RUN_ID" != *$'\r'* ]] || die "invalid ORCH_RUN_ID: path separators and traversal are not allowed"

local_base() {
  local base
  base="$(git symbolic-ref --quiet --short refs/remotes/origin/HEAD 2>/dev/null | sed 's@^origin/@@' || true)"
  [[ -n "$base" ]] || base="main"
  printf '%s\n' "$base"
}

if [[ "$DRY" == "1" ]]; then
  BASE="$(local_base)"
  echo "== orchestrate dry-run: $TOPIC =="
  echo "   plan=$PLAN_ABS  branch=$BRANCH  base=$BASE  sandbox=$SANDBOX  effort=$EXEC_EFFORT  worktree=$WORKTREE"
  [[ "$WORKTREE" == "1" ]] && echo "+ git worktree add -b '$BRANCH' <temp-worktree> 'origin/$BASE'"
  echo "+ codex exec -s read-only -c approval_policy=never -o <critique> - < <critique-prompt>"
  [[ "$WORKTREE" == "1" ]] || echo "+ git switch -c '$BRANCH'  # or reuse the existing task branch"
  echo "+ codex exec -s '$SANDBOX' -c approval_policy=never -c model_reasoning_effort='$EXEC_EFFORT' -o <implementation> - < <implementation-prompt>"
  VERIFY_NAMES="$("$VERIFY_PYTHON" "$VERIFY_HELPER" configured --config "$VERIFY_CONFIG")" || \
    die "invalid verify configuration: $VERIFY_CONFIG"
  while IFS= read -r verify_name; do
    [[ -n "$verify_name" ]] || continue
    verify_display="$("$VERIFY_PYTHON" "$VERIFY_HELPER" display --config "$VERIFY_CONFIG" --name "$verify_name")" || \
      die "invalid verify configuration: $VERIFY_CONFIG"
    echo "+ verify $verify_name (${VERIFY_TIMEOUT}s): $verify_display"
  done <<< "$VERIFY_NAMES"
  echo "+ git push -u origin '$BRANCH'"
  echo "+ gh pr create --base '$BASE' --head '$BRANCH' --fill"
  exit 0
fi

command -v codex >/dev/null || die "codex CLI not found"
command -v gh >/dev/null || die "gh CLI not found"
gh auth status >/dev/null 2>&1 || die "gh not authenticated (gh auth login)"

git fetch origin -q 2>/dev/null || true
BASE="$(git symbolic-ref --quiet --short refs/remotes/origin/HEAD 2>/dev/null | sed 's@^origin/@@' || true)"
[[ -n "$BASE" ]] || BASE="$(gh repo view --json defaultBranchRef -q .defaultBranchRef.name 2>/dev/null || true)"
[[ -n "$BASE" ]] || BASE="main"

is_linked_worktree() {
  local git_dir common_dir
  git_dir="$(cd "$(git rev-parse --git-dir)" 2>/dev/null && pwd -P)" || return 1
  common_dir="$(cd "$(git rev-parse --git-common-dir)" 2>/dev/null && pwd -P)" || return 1
  [[ "$git_dir" != "$common_dir" ]]
}

RUN_FILE="$HOME/.orchestrate/runs/$RUN_ID.json"
existing_status=""
existing_pid=""
existing_checkpoint=""
if [[ -f "$RUN_FILE" ]]; then
  existing_status="$(python3 - "$RUN_FILE" <<'PY'
import json, sys
try:
    with open(sys.argv[1]) as fh:
        run = json.load(fh)
    print(run.get("status", ""))
except Exception:
    print("")
PY
  )"
  existing_pid="$(python3 - "$RUN_FILE" <<'PY'
import json, sys
try:
    with open(sys.argv[1]) as fh:
        print(json.load(fh).get("pid") or "")
except Exception:
    print("")
PY
  )"
  existing_checkpoint="$(python3 - "$RUN_FILE" <<'PY'
import json, sys
try:
    with open(sys.argv[1]) as fh:
        print((json.load(fh).get("checkpoint") or {}).get("name", ""))
except Exception:
    print("")
PY
  )"
  if [[ "$RESUME" != "1" && ( "$existing_checkpoint" == "awaiting_approval" || "$existing_checkpoint" == "approval_granted" ) ]]; then
    die "run '$RUN_ID' has a pending push/PR continuation — use --resume from its recorded cwd"
  fi
  if [[ "$RESUME" != "1" && ( "$existing_status" == "running" || "$existing_status" == "review" ) ]]; then
    if [[ "$existing_pid" =~ ^[0-9]+$ ]] && kill -0 "$existing_pid" 2>/dev/null; then
      die "run '$RUN_ID' already live — finish or kill it first"
    fi
  fi
fi

if [[ "$RESUME" == "1" ]]; then
  [[ -f "$RUN_FILE" ]] || die "no run record found for '$RUN_ID'"
  [[ "$existing_checkpoint" == "awaiting_approval" || "$existing_checkpoint" == "approval_granted" ]] || \
    die "run '$RUN_ID' has no resumable push/PR checkpoint"
fi

MADE_BRANCH=0
if [[ "$RESUME" == "1" ]]; then
  recorded_cwd="$(python3 - "$RUN_FILE" <<'PY'
import json, sys
with open(sys.argv[1]) as fh:
    print(json.load(fh).get("cwd", ""))
PY
  )"
  recorded_branch="$(python3 - "$RUN_FILE" <<'PY'
import json, sys
with open(sys.argv[1]) as fh:
    print(json.load(fh).get("branch", ""))
PY
  )"
  recorded_worktree="$(python3 - "$RUN_FILE" <<'PY'
import json, sys
with open(sys.argv[1]) as fh:
    print("1" if (json.load(fh).get("restart") or {}).get("dedicatedWorktree") else "0")
PY
  )"
  recorded_baton_root="$(python3 - "$RUN_FILE" <<'PY'
import json, sys
with open(sys.argv[1]) as fh:
    run = json.load(fh)
print(((run.get("restart") or {}).get("env") or {}).get("ORCH_BATON_ROOT", ""))
PY
  )"
  recorded_repo_root="$(python3 - "$RUN_FILE" <<'PY'
import json, sys
with open(sys.argv[1]) as fh:
    print(json.load(fh).get("repoRoot", ""))
PY
  )"
  [[ "$(pwd -P)" == "$recorded_cwd" ]] || die "resume must run from recorded cwd: $recorded_cwd"
  [[ "$(git branch --show-current)" == "$recorded_branch" ]] || die "resume expected branch '$recorded_branch'"
  DEDICATED_WORKTREE="$recorded_worktree"
  [[ -z "$recorded_baton_root" ]] || BATON_ROOT="$recorded_baton_root"
  if [[ -n "$recorded_repo_root" ]]; then
    CONFIG_ROOT="$recorded_repo_root"
    VERIFY_CONFIG="$CONFIG_ROOT/.ai/orchestrate.toml"
  fi
  MADE_BRANCH=1
elif [[ "$RESTART" == "1" ]]; then
  [[ "$DEDICATED_WORKTREE" == "1" ]] || die "automatic restart is allowed only in a recorded dedicated worktree"
  is_linked_worktree || die "automatic restart refused: current directory is not a linked worktree"
  [[ "$(git branch --show-current)" == "$BRANCH" ]] || \
    die "automatic restart refused: expected branch '$BRANCH'"
  MADE_BRANCH=1
elif [[ "$WORKTREE" == "1" ]]; then
  WT="$(mktemp -d -t orch-wt-XXXX)"
  git worktree add -q -b "$BRANCH" "$WT" "origin/$BASE" || die "worktree add failed"
  cp "$PLAN_ABS" "$WT/$(basename "$PLAN")" || die "failed to copy plan into worktree"
  cd "$WT"
  PLAN="$(basename "$PLAN")"
  PLAN_ABS="$(pwd -P)/$PLAN"
  if [[ -n "$SELF_REL" && -f "$(pwd -P)/$SELF_REL" ]]; then
    SELF="$(pwd -P)/$SELF_REL"
  fi
  MADE_BRANCH=1
  DEDICATED_WORKTREE=1
else
  [[ -z "$(git status --porcelain)" ]] || \
    die "working tree dirty — commit/stash first, or set ORCH_WORKTREE=1"
fi

STATUS_BIN=""
for candidate in "$(dirname "$SELF")/../dashboard/orchestrate-status" \
                 "$(dirname "$SELF")/../skills/orchestrate/dashboard/orchestrate-status" \
                 "$HOME/.claude/skills/orchestrate/dashboard/orchestrate-status"; do
  [[ -x "$candidate" ]] && { STATUS_BIN="$candidate"; break; }
done
[[ -n "$STATUS_BIN" ]] || STATUS_BIN="$(command -v orchestrate-status 2>/dev/null || true)"
emit() { [[ -n "${STATUS_BIN:-}" ]] && python3 "$STATUS_BIN" "$@" >/dev/null 2>&1 || true; }
proc_start() { ps -o lstart= -p "$1" 2>/dev/null | sed 's/^[[:space:]]*//;s/[[:space:]]*$//'; }
proc_pgid() { ps -o pgid= -p "$1" 2>/dev/null | tr -d '[:space:]'; }

DRIVER_START="$(proc_start $$ || true)"
DRIVER_PGID="$(proc_pgid $$ || true)"
START_ARGS=(start --id "$RUN_ID" --repo "$REPO_NAME" --topic "$TOPIC"
  --title "${ORCH_TITLE:-$TOPIC}" --branch "$BRANCH" --pid "$$"
  --cwd "$(pwd -P)" --repo-root "$ORIG_ROOT" --driver "$SELF" --plan "$PLAN_ABS")
[[ -n "$DRIVER_START" ]] && START_ARGS+=(--pid-start "$DRIVER_START")
[[ "$DRIVER_PGID" =~ ^[0-9]+$ ]] && START_ARGS+=(--pgid "$DRIVER_PGID")
[[ "$DEDICATED_WORKTREE" == "1" ]] && START_ARGS+=(--worktree)
START_ARGS+=(--env "ORCH_SANDBOX=$SANDBOX"
  --env "ORCH_EXEC_EFFORT=$EXEC_EFFORT"
  --env "ORCH_STALL_KILL=${ORCH_STALL_KILL:-300}"
  --env "ORCH_MAX_RETRY=${ORCH_MAX_RETRY:-2}"
  --env "ORCH_VERIFY_TIMEOUT=$VERIFY_TIMEOUT"
  --env "ORCH_PYTHON=$VERIFY_PYTHON"
  --env "ORCH_TITLE=${ORCH_TITLE:-$TOPIC}"
  --env "ORCH_RUN_ID=$RUN_ID"
  --env "ORCH_REPO_NAME=$REPO_NAME"
  --env "ORCH_BATON_ROOT=$BATON_ROOT")
if [[ "$RESUME" == "1" ]]; then
  emit heartbeat --id "$RUN_ID" --pid "$$"
else
  emit "${START_ARGS[@]}"
fi

FAIL_TRAP_ARMED=1
CURRENT_STEP=1
on_exit() {
  local rc=$?
  trap - EXIT
  if [[ "$rc" -ne 0 && "${FAIL_TRAP_ARMED:-0}" == "1" ]]; then
    emit step --id "$RUN_ID" --n "${CURRENT_STEP:-1}" --state fail --note "driver aborted"
    emit fail --id "$RUN_ID"
  fi
  exit "$rc"
}
trap on_exit EXIT
[[ "$RESUME" == "1" ]] || emit step --id "$RUN_ID" --n 1 --state done

LAST_SESSION_ID=""
capture_session() {
  local log="$1" session
  session="$(sed -nE 's/.*session id:[[:space:]]*([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}).*/\1/p' "$log" | head -1)"  # header id; test output later in the log may contain fixture UUIDs
  LAST_SESSION_ID="$session"
  [[ -n "$session" ]] && emit metric --id "$RUN_ID" --key session --value "$session"
}

codex_run() { # <prompt-file> <out-file> <sandbox> <effort|""> <step-n>
  local prompt_file="$1" out_file="$2" sandbox="$3" effort="$4" step_n="$5"
  local attempt=1 max="${ORCH_MAX_RETRY:-2}" kill_after="${ORCH_STALL_KILL:-300}"
  local -a cmd=(codex exec -s "$sandbox" -c approval_policy=never)
  [[ -n "$effort" ]] && cmd+=(-c "model_reasoning_effort=$effort")
  cmd+=(-o "$out_file" -)
  while :; do
    local log cpid last_size=-1 idle=0 hung=0 rc=0 size worker_start worker_pgid last_act_t=0 act
    log="$(mktemp -t orch-clog-XXXX).log"
    [[ -n "$step_n" ]] && emit metric --id "$RUN_ID" --key log --value "$log"
    "${cmd[@]}" < "$prompt_file" >"$log" 2>&1 &
    cpid=$!
    worker_start="$(proc_start "$cpid" || true)"
    worker_pgid="$(proc_pgid "$cpid" || true)"
    if [[ -n "$worker_start" && "$worker_pgid" =~ ^[0-9]+$ ]]; then
      emit worker --id "$RUN_ID" --pid "$cpid" --pid-start "$worker_start" --pgid "$worker_pgid" --cwd "$(pwd -P)"
    fi
    while kill -0 "$cpid" 2>/dev/null; do
      sleep 1
      size="$(wc -c <"$log" 2>/dev/null || echo 0)"
      if [[ "$size" != "$last_size" ]]; then
        last_size="$size"; idle=0; emit heartbeat --id "$RUN_ID" --pid "$$"
        # stream "now doing" to the dashboard: latest codex narration or command (throttled)
        if [[ -n "$step_n" ]] && (( SECONDS - last_act_t >= 10 )); then
          last_act_t=$SECONDS
          act="$(awk '/^codex$/{p=1;next} p&&NF{print "\xc2\xb7 "$0; p=0} /^exec /{sub(/^exec [^ ]* -lc /,"$ "); sub(/ in \/[^ ]*$/,""); print}' "$log" 2>/dev/null | tail -1 | tr -d '\r' | cut -c1-110)"
          [[ -n "$act" ]] && emit step --id "$RUN_ID" --n "$step_n" --state active --note "$act" || true
        fi
      else
        idle=$((idle + 1))
      fi
      if (( idle >= kill_after )); then
        hung=1
        pkill -9 -P "$cpid" 2>/dev/null || true
        kill -9 "$cpid" 2>/dev/null || true
        wait "$cpid" 2>/dev/null || true
        break
      fi
    done
    if [[ "$hung" == "0" ]]; then
      if wait "$cpid"; then rc=0; else rc=$?; fi
      capture_session "$log"
      [[ "$rc" -eq 0 ]] && return 0
      echo "  Codex failed (log: $log)" >&2
      return "$rc"
    fi
    if (( attempt > max )); then
      emit step --id "$RUN_ID" --n "$step_n" --state fail --note "Codex hung ${kill_after}s; $max retries exhausted — escalating"
      echo "  Codex hung repeatedly (log: $log) — escalating to human" >&2
      return 124
    fi
    emit step --id "$RUN_ID" --n "$step_n" --state active --note "Codex hung — auto-recovered (retry $attempt/$max)"
    echo "  Codex: no output for ${kill_after}s — killed + retrying ($attempt/$max)" >&2
    attempt=$((attempt + 1))
  done
}

codex_resume_fix() { # <session-id> <prompt-file> <out-file>
  local session="$1" prompt_file="$2" out_file="$3"
  local kill_after="${ORCH_STALL_KILL:-300}" log cpid last_size=-1 idle=0 size rc=0
  local worker_start worker_pgid
  local -a cmd=(codex exec resume -c approval_policy=never
    -c "model_reasoning_effort=$EXEC_EFFORT" -o "$out_file" "$session" -)
  log="$(mktemp -t orch-resume-XXXX).log"
  "${cmd[@]}" < "$prompt_file" >"$log" 2>&1 &
  cpid=$!
  worker_start="$(proc_start "$cpid" || true)"
  worker_pgid="$(proc_pgid "$cpid" || true)"
  if [[ -n "$worker_start" && "$worker_pgid" =~ ^[0-9]+$ ]]; then
    emit worker --id "$RUN_ID" --pid "$cpid" --pid-start "$worker_start" --pgid "$worker_pgid" --cwd "$(pwd -P)"
  fi
  while kill -0 "$cpid" 2>/dev/null; do
    sleep 1
    size="$(wc -c <"$log" 2>/dev/null || echo 0)"
    if [[ "$size" != "$last_size" ]]; then
      last_size="$size"; idle=0; emit heartbeat --id "$RUN_ID" --pid "$$"
    else
      idle=$((idle + 1))
    fi
    if (( idle >= kill_after )); then
      pkill -9 -P "$cpid" 2>/dev/null || true
      kill -9 "$cpid" 2>/dev/null || true
      wait "$cpid" 2>/dev/null || true
      echo "  Codex repair produced no output for ${kill_after}s (log: $log)" >&2
      return 124
    fi
  done
  if wait "$cpid"; then rc=0; else rc=$?; fi
  capture_session "$log"
  if [[ "$rc" -ne 0 ]]; then
    echo "  Codex repair failed (log: $log)" >&2
  fi
  return "$rc"
}

ARTIFACT_DIR="$HOME/.orchestrate/artifacts/$RUN_ID"
mkdir -p "$ARTIFACT_DIR"
CRIT="$ARTIFACT_DIR/critique.md"
IMPL="$ARTIFACT_DIR/implementation.md"
VERIFY_FAILED_NAME=""
VERIFY_FAILED_DISPLAY=""
VERIFY_FAILED_LOG=""

run_verification() {
  local names name shown summary rc metric=""
  if ! names="$("$VERIFY_PYTHON" "$VERIFY_HELPER" configured --config "$VERIFY_CONFIG")"; then
    return 2
  fi
  if [[ -z "$names" ]]; then
    emit metric --id "$RUN_ID" --key verify --value "none"
    echo "   verify gate: no commands configured"
    return 0
  fi
  while IFS= read -r name; do
    [[ -n "$name" ]] || continue
    shown="$("$VERIFY_PYTHON" "$VERIFY_HELPER" display --config "$VERIFY_CONFIG" --name "$name")" || return 2
    summary="$ARTIFACT_DIR/verify-${name}.json"
    echo "   verifying: $shown"
    emit step --id "$RUN_ID" --n 3 --state active --note "verifying: ${shown:0:100}"
    if "$VERIFY_PYTHON" "$VERIFY_HELPER" run --config "$VERIFY_CONFIG" --name "$name" \
      --workdir "$(pwd -P)" --artifact-dir "$ARTIFACT_DIR" \
      --timeout "$VERIFY_TIMEOUT" --summary "$summary"; then
      metric="${metric:+$metric }${name}=pass"
    else
      rc=$?
      [[ "$rc" -eq 1 ]] || return 2
      VERIFY_FAILED_NAME="$name"
      VERIFY_FAILED_DISPLAY="$shown"
      VERIFY_FAILED_LOG="$ARTIFACT_DIR/verify-${name}.log"
      metric="${metric:+$metric }${name}=fail"
      emit metric --id "$RUN_ID" --key verify --value "$metric"
      return 1
    fi
  done <<< "$names"
  emit metric --id "$RUN_ID" --key verify --value "$metric"
  return 0
}

if [[ "$RESUME" != "1" ]]; then
  echo "== orchestrate: $TOPIC =="
  echo "   plan=$PLAN  branch=$BRANCH  base=$BASE  sandbox=$SANDBOX  effort=$EXEC_EFFORT  worktree=$DEDICATED_WORKTREE"

  CURRENT_STEP=2
  echo "-- [2/4] Codex critiques the plan (read-only)"
  emit step --id "$RUN_ID" --n 2 --state active
  CPROMPT="$(mktemp -t orch-cprompt-XXXX).md"
  {
    printf 'You are an elite engineer. Critique this plan for a change in %s: risks, wrong assumptions, missing edge cases, simpler approaches, and anything that would make a reviewer reject the PR. Be specific and terse. Plan follows:\n\n' "$(pwd)"
    cat "$PLAN"
  } > "$CPROMPT"
  codex_run "$CPROMPT" "$CRIT" read-only "" 2 || die "critique step failed (see log above)"
  echo "   critique -> $CRIT"

  CURRENT_STEP=3
  emit step --id "$RUN_ID" --n 2 --state done
  echo "-- [3/4] Codex implements on $BRANCH (sandbox=$SANDBOX, effort=$EXEC_EFFORT, no network)"
  emit step --id "$RUN_ID" --n 3 --state active
  if [[ "$MADE_BRANCH" != "1" ]]; then
    if git show-ref --verify --quiet "refs/heads/$BRANCH"; then
      git switch "$BRANCH"
    else
      git switch -c "$BRANCH"
    fi
  fi
  BEFORE="$(git rev-parse HEAD 2>/dev/null || true)"
  IPROMPT="$(mktemp -t orch-iprompt-XXXX).md"
  if [[ "$DEDICATED_WORKTREE" == "1" ]]; then
    printf 'Implement the plan in %s on the current branch (%s). Consider the critique at %s. Run the project'"'"'s tests/lint/build until green. Do NOT stage or commit: this linked worktree'"'"'s git metadata is outside your sandbox, so the driver will commit after you finish. For any gated action, stop and emit "⛔ APPROVAL-REQUEST: <action> — <why>". Do NOT push and do NOT open a PR. End your response with a one-line summary suitable for use as the commit subject.\n' "$PLAN" "$BRANCH" "$CRIT" > "$IPROMPT"
  else
    printf 'Implement the plan in %s on the current branch (%s). Consider the critique at %s. Run the project'"'"'s tests/lint/build until green. Then stage and git commit with a clear message. For any gated action, stop and emit "⛔ APPROVAL-REQUEST: <action> — <why>". Do NOT push and do NOT open a PR — the sandbox has no network; the driver handles that. Summarize what you changed on the last line.\n' "$PLAN" "$BRANCH" "$CRIT" > "$IPROMPT"
  fi
  codex_run "$IPROMPT" "$IMPL" "$SANDBOX" "$EXEC_EFFORT" 3 || die "implement step failed"
  IMPL_SESSION_ID="$LAST_SESSION_ID"
  [[ -n "$IMPL_SESSION_ID" ]] || die "implementation completed but no Codex session id was captured"
else
  echo "== orchestrate: resuming approval for $TOPIC =="
  IMPL_SESSION_ID="$(python3 - "$RUN_FILE" <<'PY'
import json, sys
with open(sys.argv[1]) as fh:
    print((json.load(fh).get("metrics") or {}).get("session", ""))
PY
  )"
  [[ -n "$IMPL_SESSION_ID" ]] || die "run record has no implementation session"
  [[ -f "$IMPL" ]] || die "implementation artifact missing: $IMPL"
  BEFORE="$(git merge-base HEAD "origin/$BASE" 2>/dev/null || git rev-parse HEAD)"
fi

APPROVAL_REQUEST="$(sed -n 's/^⛔ APPROVAL-REQUEST:[[:space:]]*//p' "$IMPL" | head -1)"
if [[ "$RESUME" != "1" && -n "$APPROVAL_REQUEST" ]]; then
  APPROVAL_REQUEST="${APPROVAL_REQUEST:0:500}"
  [[ -n "$STATUS_BIN" ]] || die "approval requested but orchestrate-status is unavailable"
  python3 "$STATUS_BIN" gate --id "$RUN_ID" --kind approval \
    --checkpoint awaiting_approval --continuation push_pr \
    --question "$APPROVAL_REQUEST" \
    --option "Approve and continue:primary" --option "Reject and stop" >/dev/null || \
    die "could not persist approval gate"
fi

if [[ "$RESUME" == "1" || -n "$APPROVAL_REQUEST" ]]; then
  [[ -n "$STATUS_BIN" ]] || die "approval requested but orchestrate-status is unavailable"
  saved_choice="$(python3 - "$RUN_FILE" <<'PY'
import json, sys
with open(sys.argv[1]) as fh:
    print((json.load(fh).get("lastGateAnswer") or {}).get("choice", ""))
PY
  )"
  if [[ "$existing_checkpoint" == "approval_granted" ]]; then
    choice="Approve and continue"
  elif [[ "$saved_choice" == "Approve and continue" ]]; then
    choice="$saved_choice"
  elif choice="$(python3 "$STATUS_BIN" wait --id "$RUN_ID" --timeout "$GATE_TIMEOUT")"; then
    :
  else
    wait_rc=$?
    if [[ "$wait_rc" -eq 2 ]]; then
      emit pause --id "$RUN_ID"
      FAIL_TRAP_ARMED=0
      echo "orchestrate: approval timed out; gate preserved. Resume from this cwd with: $SELF --resume --timeout 0 $TOPIC $PLAN" >&2
      exit 2
    fi
    die "approval wait failed"
  fi
  if [[ "$choice" == "Reject and stop" ]]; then
    emit cancel --id "$RUN_ID" --reason "approval rejected: ${APPROVAL_REQUEST:-requested action}"
    FAIL_TRAP_ARMED=0
    echo "orchestrate: approval rejected; push/PR skipped" >&2
    exit 3
  fi
  [[ "$choice" == "Approve and continue" ]] || die "unexpected approval choice: $choice"
  python3 "$STATUS_BIN" checkpoint --id "$RUN_ID" --name approval_granted \
    --continuation push_pr >/dev/null || die "could not persist approved continuation"
fi

echo "-- [3/4] independent verify gate"
if run_verification; then
  :
else
  verify_rc=$?
  [[ "$verify_rc" -eq 1 ]] || die "invalid verify configuration: $VERIFY_CONFIG"
  echo "   $VERIFY_FAILED_NAME verification failed; resuming Codex once (log: $VERIFY_FAILED_LOG)" >&2
  emit step --id "$RUN_ID" --n 3 --state active --note "verify failed: $VERIFY_FAILED_NAME; one repair attempt"
  VPROMPT="$(mktemp -t orch-vprompt-XXXX).md"
  VOUT="$ARTIFACT_DIR/verify-repair.md"
  {
    printf 'Independent verification failed for this command:\n  %s\n\n' "$VERIFY_FAILED_DISPLAY"
    printf 'Fix the underlying code or configuration only. Do not run the verification command yourself; the driver is the sole verifier and will rerun all configured commands. Do not stage, commit, push, or open a PR. For any gated action, stop and emit "⛔ APPROVAL-REQUEST: <action> — <why>". Last output follows:\n\n'
    tail -80 "$VERIFY_FAILED_LOG"
  } > "$VPROMPT"
  codex_resume_fix "$IMPL_SESSION_ID" "$VPROMPT" "$VOUT" || die "verification repair session failed"
  REPAIR_APPROVAL="$(sed -n 's/^⛔ APPROVAL-REQUEST:[[:space:]]*//p' "$VOUT" | head -1)"
  [[ -z "$REPAIR_APPROVAL" ]] || die "verification repair requires approval before continuing: ${REPAIR_APPROVAL:0:500}"
  if run_verification; then
    :
  else
    verify_rc=$?
    [[ "$verify_rc" -eq 1 ]] || die "invalid verify configuration after repair: $VERIFY_CONFIG"
    die "$VERIFY_FAILED_NAME verification still failing after one repair (log: $VERIFY_FAILED_LOG); push/PR skipped"
  fi
fi

COMMIT_SUBJECT="$(awk 'NF { line=$0 } END { print line }' "$IMPL" | tr -d '\r')"
[[ -n "$COMMIT_SUBJECT" ]] || COMMIT_SUBJECT="orchestrate: $TOPIC"
COMMIT_SUBJECT="${COMMIT_SUBJECT:0:200}"
git add -A -- ':!PLAN-*.md' || die "driver could not stage verified changes"
if git diff --cached --quiet; then
  ALREADY_AHEAD="$(git rev-list --count "origin/$BASE..HEAD" 2>/dev/null || echo 0)"
  [[ "$DEDICATED_WORKTREE" != "1" || ( "$RESUME" == "1" && "$ALREADY_AHEAD" -ge 1 ) ]] || \
    die "Codex changed nothing in the worktree (see $IMPL) — aborting."
else
  git commit -m "$COMMIT_SUBJECT" || die "driver could not commit verified changes"
fi

CURRENT_STEP=4
emit step --id "$RUN_ID" --n 3 --state done
echo "-- [4/4] push branch + open PR (base: $BASE)"
emit step --id "$RUN_ID" --n 4 --state active
AHEAD="$(git rev-list --count "${BEFORE:+$BEFORE..}HEAD" 2>/dev/null || echo 0)"
if [[ "$DEDICATED_WORKTREE" == "1" ]]; then
  [[ "$AHEAD" -ge 1 ]] || die "driver commit did not land on $BRANCH (see $IMPL) — aborting."
else
  [[ "$AHEAD" -ge 1 ]] || die "Codex committed nothing on $BRANCH (see $IMPL) — aborting."
fi
TEST_DELTA="$("$VERIFY_PYTHON" "$VERIFY_HELPER" classify --repo "$(pwd -P)" --base-ref "origin/$BASE")" || \
  die "could not classify test delta against origin/$BASE"
emit metric --id "$RUN_ID" --key testDelta --value "$TEST_DELTA"
TEST_DELTA_WARNING=""
if [[ "$TEST_DELTA" == "src-only" ]]; then
  TEST_DELTA_WARNING="- ⚠ diff changes source but no tests — scrutinize coverage"
fi
git push -u origin "$BRANCH" || die "git push failed"
gh pr view "$BRANCH" >/dev/null 2>&1 || \
  gh pr create --base "$BASE" --head "$BRANCH" --fill >/dev/null || \
    { sleep 5; gh pr create --base "$BASE" --head "$BRANCH" --fill >/dev/null; } || die "gh pr create failed"  # retry once: transient TLS/API blips
PR_NUM="$(gh pr view "$BRANCH" --json number -q .number)"
PR_URL="$(gh pr view "$BRANCH" --json url -q .url)"
emit pr --id "$RUN_ID" --number "$PR_NUM" --url "$PR_URL"
emit step --id "$RUN_ID" --n 4 --state done
emit step --id "$RUN_ID" --n 5 --state active

BATON="$BATON_ROOT/HANDOFF-CLAUDE-review-${TOPIC}.md"
cat > "$BATON" <<EOF
# Handoff for Claude — review PR #${PR_NUM}

## Mission
- Review PR #${PR_NUM} (${PR_URL}) on branch ${BRANCH} (base ${BASE}). Lens: correctness, taste, security, contract.

## Read First
- \`gh pr diff ${PR_NUM}\`
- Codex critique: ${CRIT}
- Codex implementation notes: ${IMPL}
- Codex implementation session: ${IMPL_SESSION_ID}
$TEST_DELTA_WARNING
$([[ "$DEDICATED_WORKTREE" == "1" ]] && echo "- Worktree with the changes: $(pwd)  (git worktree remove it when done)")

## Definition of Done
- Post review (blocking/notable/nit). Blocking findings return to the exact Codex session:
  \`codex exec resume ${IMPL_SESSION_ID} ...\`
- Clean + low-risk + CI green proceeds to the deploy gate in the Claude session.
EOF

REVIEW_COMMAND="/orchestrate review ${TOPIC}"
emit handoff --id "$RUN_ID" --baton "$BATON" --review-command "$REVIEW_COMMAND" --max-iterations 3
FAIL_TRAP_ARMED=0
echo
echo "== Codex leg done. PR #${PR_NUM} ready for Claude review."
echo "   Baton: ${BATON}"
[[ "$DEDICATED_WORKTREE" == "1" ]] && echo "   Worktree: $(pwd)"
echo "   Resume steps 5–7 in Claude: $REVIEW_COMMAND"
