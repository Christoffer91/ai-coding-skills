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
#   ORCH_EXEC_MODEL   implement model when no override is active (default gpt-5.6-terra)
#   ORCH_EXEC_EFFORT  low|medium|high|xhigh|ultra (default medium)
#   ORCH_PROFILE      DIRECT|FAST|STANDARD|DEEP (default STANDARD)
#   ORCH_TOKEN_POLICY observe|enforce (default observe)
#   ORCH_TOKEN_NEXT_SPAWN_LIMIT optional observed-token threshold for another model call
#   ORCH_WORKTREE=1   create a dedicated worktree off origin/<default-branch>
#   ORCH_STALL_KILL   seconds without Codex output before retry (default 300)
#   ORCH_MAX_RETRY    retry count after a hung step (default 2)
#   ORCH_TITLE        dashboard card title (default topic)
#   ORCH_GATE_TIMEOUT seconds to wait for a gate; 0 waits forever (default 0)
#   ORCH_VERIFY_TIMEOUT seconds allowed per configured verify command (default 900)
#   ORCH_OVERRIDE_PATH fixture override store for deterministic dry-runs/tests
#   ORCH_CLAUDE_BIN   absolute Claude Code CLI path; otherwise prefer ~/.local/bin/claude
#   ORCH_CLAUDE_MAX_BUDGET_USD optional subscription cap; metered/API auth defaults to 2
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
EXEC_MODEL="${ORCH_EXEC_MODEL:-gpt-5.6-terra}"
EXEC_EFFORT="${ORCH_EXEC_EFFORT:-medium}"
EFFORT_SOURCE="default"
[[ -n "${ORCH_EXEC_EFFORT+x}" ]] && EFFORT_SOURCE="env"
WORKTREE="${ORCH_WORKTREE:-0}"
DRY="${ORCH_DRYRUN:-0}"
RESTART="${ORCH_RESTART:-0}"
DEDICATED_WORKTREE="${ORCH_DEDICATED_WORKTREE:-$WORKTREE}"
VERIFY_TIMEOUT="${ORCH_VERIFY_TIMEOUT:-900}"
CALLER_ORCH_PROFILE="${ORCH_PROFILE-}"
CALLER_TOKEN_POLICY="${ORCH_TOKEN_POLICY-}"
CALLER_TOKEN_NEXT_SPAWN_LIMIT="${ORCH_TOKEN_NEXT_SPAWN_LIMIT-}"
ORCH_PROFILE="${ORCH_PROFILE:-STANDARD}"
TOKEN_POLICY="${ORCH_TOKEN_POLICY:-observe}"
TOKEN_NEXT_SPAWN_LIMIT="${ORCH_TOKEN_NEXT_SPAWN_LIMIT:-}"

is_int64_nonnegative() {
  local value="$1"
  [[ "$value" =~ ^(0|[1-9][0-9]*)$ ]] || return 1
  (( ${#value} < 19 )) || [[ ${#value} -eq 19 && "$value" < "9223372036854775808" ]]
}

canonical_decimal() {
  local value="$1"
  [[ "$value" =~ ^[0-9]+$ ]] || return 1
  while [[ ${#value} -gt 1 && "$value" == 0* ]]; do value="${value#0}"; done
  is_int64_nonnegative "$value" || return 1
  printf '%s\n' "$value"
}

can_add_int64() { # <current> <increment>
  local current="$1" increment="$2"
  is_int64_nonnegative "$current" && is_int64_nonnegative "$increment" || return 1
  (( 10#$current <= 9223372036854775807 - 10#$increment ))
}

configure_token_policy() {
  case "$ORCH_PROFILE" in
    DIRECT) DEFAULT_TOKEN_NEXT_SPAWN_LIMIT=100000 ;;
    FAST) DEFAULT_TOKEN_NEXT_SPAWN_LIMIT=250000 ;;
    STANDARD) DEFAULT_TOKEN_NEXT_SPAWN_LIMIT=600000 ;;
    DEEP) DEFAULT_TOKEN_NEXT_SPAWN_LIMIT=1200000 ;;
    *) die "ORCH_PROFILE must be one of: DIRECT, FAST, STANDARD, DEEP" ;;
  esac
  TOKEN_NEXT_SPAWN_LIMIT="${TOKEN_NEXT_SPAWN_LIMIT:-$DEFAULT_TOKEN_NEXT_SPAWN_LIMIT}"
  case "$TOKEN_POLICY" in observe|enforce) ;; *)
    die "ORCH_TOKEN_POLICY must be one of: observe, enforce" ;;
  esac
  TOKEN_NEXT_SPAWN_LIMIT="$(canonical_decimal "$TOKEN_NEXT_SPAWN_LIMIT" 2>/dev/null || true)"
  is_int64_nonnegative "$TOKEN_NEXT_SPAWN_LIMIT" && [[ "$TOKEN_NEXT_SPAWN_LIMIT" != "0" ]] || \
    die "ORCH_TOKEN_NEXT_SPAWN_LIMIT must be a positive signed 64-bit integer"
}

[[ "$RESUME" == "1" ]] || configure_token_policy

case "$EXEC_EFFORT" in low|medium|high|xhigh|ultra) ;; *)
  die "ORCH_EXEC_EFFORT must be one of: low, medium, high, xhigh, ultra" ;;
esac
[[ "$EXEC_MODEL" =~ ^[a-zA-Z0-9._-]{1,64}$ ]] || \
  die "ORCH_EXEC_MODEL must match ^[a-zA-Z0-9._-]{1,64}\$"
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

STATUS_BIN=""
for candidate in "$(dirname "$SELF")/../dashboard/orchestrate-status" \
                 "$(dirname "$SELF")/../claude/skills/orchestrate/dashboard/orchestrate-status" \
                 "$HOME/.claude/skills/orchestrate/dashboard/orchestrate-status"; do
  [[ -x "$candidate" ]] && { STATUS_BIN="$candidate"; break; }
done
[[ -n "$STATUS_BIN" ]] || STATUS_BIN="$(command -v orchestrate-status 2>/dev/null || true)"

# Resolve once per logical step. The JSON payload is parsed by Python rather
# than shell-split, and retries reuse these globals for deterministic execution.
OVERRIDE_PROVIDER="codex"
OVERRIDE_MODEL=""
OVERRIDE_EFFORT=""
OVERRIDE_SOURCE="$EFFORT_SOURCE"
OVERRIDE_ID=""
OVERRIDE_SET_AT=""
OVERRIDE_EXPIRES_AT=""
resolve_override() { # <role> <configured-effort>
  local role="$1" configured_effort="$2" payload
  OVERRIDE_PROVIDER="codex"; OVERRIDE_MODEL=""; OVERRIDE_EFFORT="$configured_effort"
  OVERRIDE_SOURCE="$EFFORT_SOURCE"; OVERRIDE_ID=""; OVERRIDE_SET_AT=""; OVERRIDE_EXPIRES_AT=""
  # A dry run is host-state-independent unless a fixture store is explicitly supplied.
  [[ "$DRY" == "1" && -z "${ORCH_OVERRIDE_PATH:-}" ]] && return 0
  [[ -n "$STATUS_BIN" ]] || return 0
  payload="$("$STATUS_BIN" overrides get --role "$role")" || die "cannot read model overrides"
  local field count=0
  while IFS= read -r field; do
    case "$count" in
      0) OVERRIDE_PROVIDER="$field" ;;
      1) OVERRIDE_MODEL="$field" ;;
      2) OVERRIDE_EFFORT="$field" ;;
      3) OVERRIDE_SOURCE="$field" ;;
      4) OVERRIDE_ID="$field" ;;
      5) OVERRIDE_SET_AT="$field" ;;
      6) OVERRIDE_EXPIRES_AT="$field" ;;
    esac
    count=$((count + 1))
  done < <(ORCH_OVERRIDE_JSON="$payload" "$VERIFY_PYTHON" - "$role" "$configured_effort" "$EFFORT_SOURCE" <<'PY'
import json, os, sys
data = json.loads(os.environ["ORCH_OVERRIDE_JSON"])
entry = (data.get("overrides") or {}).get(sys.argv[1])
if entry:
    values = [entry.get("provider", "codex"), entry.get("model", ""), entry.get("effort", sys.argv[2]),
              "override", entry.get("id", ""), str(entry.get("setAt", "")), str(entry.get("expiresAt", ""))]
else:
    values = ["codex", "", sys.argv[2], sys.argv[3], "", "", ""]
print("\n".join(values))
PY
)
  ((count == 7)) || die "override resolver returned an invalid response"
}

print_step_command() { # <role> <sandbox> <effort>
  local role="$1" sandbox="$2" effort="$3"
  resolve_override "$role" "$effort"
  if [[ "$OVERRIDE_PROVIDER" == "claude" ]]; then
    printf '+ claude -p --safe-mode --model %q --permission-mode plan --tools %q --no-session-persistence --effort max --output-format json --json-schema <review-schema>' "$OVERRIDE_MODEL" ""
    [[ "$OVERRIDE_MODEL" == "fable" ]] && printf ' --fallback-model opus'
    printf '  # budget depends on authenticated billing mode\n'
  else
    printf '+ codex exec -s %q -c approval_policy=never' "$sandbox"
    if [[ -n "$OVERRIDE_MODEL" ]]; then
      printf ' -m %q' "$OVERRIDE_MODEL"
    elif [[ "$OVERRIDE_SOURCE" != "override" && "$role" == "implement" ]]; then
      printf ' -m %q' "$EXEC_MODEL"
    fi
    [[ -n "$OVERRIDE_EFFORT" ]] && printf ' -c model_reasoning_effort=%q' "$OVERRIDE_EFFORT"
    printf ' --json -o <output> - < <prompt>\n'
  fi
}

if [[ "$DRY" == "1" ]]; then
  BASE="$(local_base)"
  echo "== orchestrate dry-run: $TOPIC =="
  echo "   plan=$PLAN_ABS  branch=$BRANCH  base=$BASE  sandbox=$SANDBOX  effort=$EXEC_EFFORT  worktree=$WORKTREE"
  echo "   profile=$ORCH_PROFILE  token-policy=$TOKEN_POLICY  next-spawn-threshold=$TOKEN_NEXT_SPAWN_LIMIT measured tokens"
  [[ "$WORKTREE" == "1" ]] && echo "+ git worktree add -b '$BRANCH' <temp-worktree> 'origin/$BASE'"
  print_step_command critique read-only ""
  [[ "$WORKTREE" == "1" ]] || echo "+ git switch -c '$BRANCH'  # or reuse the existing task branch"
  print_step_command implement "$SANDBOX" "$EXEC_EFFORT"
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
  persisted_token_env=()
  while IFS= read -r persisted; do
    persisted_token_env+=("$persisted")
  done < <("$VERIFY_PYTHON" - "$RUN_FILE" <<'PY'
import json, sys
with open(sys.argv[1]) as fh:
    env = ((json.load(fh).get("restart") or {}).get("env") or {})
for key in ("ORCH_PROFILE", "ORCH_TOKEN_POLICY", "ORCH_TOKEN_NEXT_SPAWN_LIMIT"):
    print(str(env.get(key, "")))
PY
  )
  for index in 0 1 2; do
    persisted="${persisted_token_env[$index]:-}"
    caller=("$CALLER_ORCH_PROFILE" "$CALLER_TOKEN_POLICY" "$CALLER_TOKEN_NEXT_SPAWN_LIMIT")
    names=("ORCH_PROFILE" "ORCH_TOKEN_POLICY" "ORCH_TOKEN_NEXT_SPAWN_LIMIT")
    [[ -z "$persisted" ]] && continue
    [[ -z "${caller[$index]}" || "${caller[$index]}" == "$persisted" ]] || \
      die "resume ${names[$index]} conflicts with persisted value '$persisted'"
    case "$index" in
      0) ORCH_PROFILE="$persisted" ;;
      1) TOKEN_POLICY="$persisted" ;;
      2) TOKEN_NEXT_SPAWN_LIMIT="$persisted" ;;
    esac
  done
fi

[[ "$RESUME" == "1" ]] && configure_token_policy

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
  --env "ORCH_PROFILE=$ORCH_PROFILE"
  --env "ORCH_TOKEN_POLICY=$TOKEN_POLICY"
  --env "ORCH_TOKEN_NEXT_SPAWN_LIMIT=$TOKEN_NEXT_SPAWN_LIMIT"
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
emit metric --id "$RUN_ID" --key "tokens.profile" --value "$ORCH_PROFILE"
emit metric --id "$RUN_ID" --key "tokens.policy" --value "$TOKEN_POLICY"
emit metric --id "$RUN_ID" --key "tokens.nextSpawnLimit" --value "$TOKEN_NEXT_SPAWN_LIMIT"

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
  session="$("$VERIFY_PYTHON" - "$log" <<'PY' 2>/dev/null || true
import json, sys
found = []
for line in open(sys.argv[1], encoding="utf-8", errors="replace"):
    try: event = json.loads(line)
    except json.JSONDecodeError: continue
    if not isinstance(event, dict) or event.get("type") != "thread.started": continue
    value = event.get("thread_id", event.get("threadId"))
    if isinstance(value, str) and value and value.isprintable(): found.append(value)
if len(found) == 1: print(found[0])
PY
  )"
  LAST_SESSION_ID="$session"
  [[ -n "$session" ]] && emit metric --id "$RUN_ID" --key session --value "$session"
}

# Cumulative observed token count across model calls. Coverage is model calls with
# parseable token metadata divided by model calls started; dashboard steps are not
# used as the denominator because one step may contain retries or repair calls.
TOKENS_TOTAL=0
TOKENS_CRITIQUE=0
TOKENS_IMPLEMENT=0
TOKENS_REPAIR=0
TOKENS_CLAUDE=0
TOKENS_CALLS_STARTED=0
TOKENS_CALLS_OBSERVED=0
TOKEN_COVERAGE_KNOWN=1
STEP_TOKENS=(0 0 0 0 0 0 0 0)

restore_token_state() {
  [[ "$RESUME" == "1" && -f "$RUN_FILE" ]] || return 0
  local field count=0 restored=()
  while IFS= read -r field; do
    restored+=("$field")
    count=$((count + 1))
  done < <("$VERIFY_PYTHON" - "$RUN_FILE" <<'PY'
import json, re, sys
MAX = 9223372036854775807
try:
    with open(sys.argv[1]) as fh:
        run = json.load(fh)
except (OSError, json.JSONDecodeError):
    sys.exit(1)
state = (run.get("metrics") or {}).get("tokens.state.v1")
if isinstance(state, str):
    try: state = json.loads(state)
    except json.JSONDecodeError: state = None
def dec(value): return isinstance(value, str) and re.fullmatch(r"0|[1-9][0-9]*", value) and int(value) <= MAX
try:
    assert isinstance(state, dict) and type(state.get("v")) is int and state["v"] == 1
    assert type(state.get("coverageKnown")) is bool
    roles, steps = state["roles"], state["steps"]
    assert isinstance(roles, dict) and isinstance(steps, list) and len(steps) == 7
    values = [state["total"], roles["critique"], roles["implement"], roles["repair"], roles["claude"], state["callsObserved"], state["callsStarted"], *steps]
    assert all(dec(v) for v in values)
    ints = list(map(int, values)); assert ints[5] <= ints[6] and ints[0] == sum(ints[1:5]) == sum(ints[7:])
except (AssertionError, KeyError, TypeError): sys.exit(1)
print("\n".join(values + [str(state["coverageKnown"]).lower()]))
PY
  )
  if (( count != 15 )); then TOKEN_COVERAGE_KNOWN=0; TOKEN_POLICY=observe; return 0; fi
  TOKENS_TOTAL="${restored[0]}"; TOKENS_CRITIQUE="${restored[1]}"; TOKENS_IMPLEMENT="${restored[2]}"; TOKENS_REPAIR="${restored[3]}"; TOKENS_CLAUDE="${restored[4]}"; TOKENS_CALLS_OBSERVED="${restored[5]}"; TOKENS_CALLS_STARTED="${restored[6]}"
  for index in {1..7}; do STEP_TOKENS[$index]="${restored[$((index + 6))]}"; done
  [[ "${restored[14]}" == "true" ]] || { TOKEN_COVERAGE_KNOWN=0; TOKEN_POLICY=observe; }
}

emit_token_coverage() {
  if [[ "$TOKEN_COVERAGE_KNOWN" != "1" ]]; then
    emit metric --id "$RUN_ID" --key "tokens.coverage.calls.v1" --value unknown
    return 0
  fi
  emit metric --id "$RUN_ID" --key "tokens.coverage.calls.v1" \
    --value "$TOKENS_CALLS_OBSERVED/$TOKENS_CALLS_STARTED"
}

emit_token_state() {
  local snapshot
  snapshot="$(printf '{"v":1,"coverageKnown":%s,"total":"%s","roles":{"critique":"%s","implement":"%s","repair":"%s","claude":"%s"},"steps":["%s","%s","%s","%s","%s","%s","%s"],"callsStarted":"%s","callsObserved":"%s"}' "$([[ "$TOKEN_COVERAGE_KNOWN" == "1" ]] && printf true || printf false)" "$TOKENS_TOTAL" "$TOKENS_CRITIQUE" "$TOKENS_IMPLEMENT" "$TOKENS_REPAIR" "$TOKENS_CLAUDE" "${STEP_TOKENS[1]}" "${STEP_TOKENS[2]}" "${STEP_TOKENS[3]}" "${STEP_TOKENS[4]}" "${STEP_TOKENS[5]}" "${STEP_TOKENS[6]}" "${STEP_TOKENS[7]}" "$TOKENS_CALLS_STARTED" "$TOKENS_CALLS_OBSERVED")"
  emit metric --id "$RUN_ID" --key "tokens.state.v1" --value "$snapshot"
}

restore_token_state
emit_token_coverage
emit metric --id "$RUN_ID" --key "tokens.policy" --value "$TOKEN_POLICY"

before_model_call() { # <role>
  local role="$1"
  if (( TOKENS_TOTAL >= TOKEN_NEXT_SPAWN_LIMIT )); then
    emit metric --id "$RUN_ID" --key "tokens.nextSpawn" \
      --value "$TOKEN_POLICY:$ORCH_PROFILE:$TOKENS_TOTAL/$TOKEN_NEXT_SPAWN_LIMIT:$role"
    if [[ "$TOKEN_POLICY" == "enforce" ]]; then
      echo "orchestrate: next model call '$role' blocked at ${TOKENS_TOTAL}/${TOKEN_NEXT_SPAWN_LIMIT} measured tokens" >&2
      return 42
    fi
    echo "orchestrate: token observation threshold reached (${TOKENS_TOTAL}/${TOKEN_NEXT_SPAWN_LIMIT}); continuing '$role' in observe mode" >&2
  fi
  if can_add_int64 "$TOKENS_CALLS_STARTED" 1; then
    TOKENS_CALLS_STARTED=$((TOKENS_CALLS_STARTED + 1))
  else
    TOKEN_COVERAGE_KNOWN=0
  fi
  emit_token_coverage
  emit_token_state
}

record_token_value() { # <tokens> <role> [step_n]
  local tokens="$1" role="$2" step_n="${3:-}" role_total role_counter=""
  TOKEN_VALUE_RECORDED=0
  is_int64_nonnegative "$tokens" || return 0
  case "$role" in
    critique) role_counter="$TOKENS_CRITIQUE" ;;
    implement) role_counter="$TOKENS_IMPLEMENT" ;;
    repair) role_counter="$TOKENS_REPAIR" ;;
    claude*) role_counter="$TOKENS_CLAUDE" ;;
  esac
  # Check every token aggregate before mutating any of them. A bad telemetry value
  # must not wrap or leave a partial total behind.
  can_add_int64 "$TOKENS_TOTAL" "$tokens" || return 0
  [[ -z "$role_counter" ]] || can_add_int64 "$role_counter" "$tokens" || return 0
  if [[ -n "$step_n" && "$step_n" =~ ^[1-7]$ ]]; then
    can_add_int64 "${STEP_TOKENS[$step_n]}" "$tokens" || return 0
  fi
  TOKENS_TOTAL=$((TOKENS_TOTAL + 10#$tokens))
  case "$role" in
    critique) TOKENS_CRITIQUE=$((TOKENS_CRITIQUE + 10#$tokens)); role_total=$TOKENS_CRITIQUE ;;
    implement) TOKENS_IMPLEMENT=$((TOKENS_IMPLEMENT + 10#$tokens)); role_total=$TOKENS_IMPLEMENT ;;
    repair) TOKENS_REPAIR=$((TOKENS_REPAIR + 10#$tokens)); role_total=$TOKENS_REPAIR ;;
    claude*) TOKENS_CLAUDE=$((TOKENS_CLAUDE + 10#$tokens)); role_total=$TOKENS_CLAUDE ;;
    *) role_total=$tokens ;;
  esac
  emit metric --id "$RUN_ID" --key "tokens.$role" --value "$role_total"
  emit metric --id "$RUN_ID" --key "tokens.total" --value "$TOKENS_TOTAL"
  if can_add_int64 "$TOKENS_CALLS_OBSERVED" 1; then
    TOKENS_CALLS_OBSERVED=$((TOKENS_CALLS_OBSERVED + 1))
  else
    TOKEN_COVERAGE_KNOWN=0
  fi
  emit_token_coverage
  if [[ -n "$step_n" && "$step_n" =~ ^[1-7]$ ]]; then
    STEP_TOKENS[$step_n]=$((STEP_TOKENS[$step_n] + 10#$tokens))
    emit step --id "$RUN_ID" --n "$step_n" --tokens "${STEP_TOKENS[$step_n]}"
  fi
  emit_token_state
  TOKEN_VALUE_RECORDED=1
}

capture_tokens() { # <log> <role> [step_n]
  local log="$1" role="$2" step_n="${3:-}" tokens=""
  [[ -n "$role" && -f "$log" ]] || return 0
  tokens="$("$VERIFY_PYTHON" - "$log" <<'PY' 2>/dev/null || true
import json, sys
MAX=9223372036854775807; completed=[]
for line in open(sys.argv[1], encoding="utf-8", errors="replace"):
    try: event=json.loads(line)
    except json.JSONDecodeError: continue
    if not isinstance(event, dict) or event.get("type") != "turn.completed": continue
    completed.append(event)
if len(completed)==1:
    usage=completed[0].get("usage"); inp=usage.get("input_tokens") if isinstance(usage,dict) else None; out=usage.get("output_tokens") if isinstance(usage,dict) else None
    if isinstance(inp,int) and not isinstance(inp,bool) and isinstance(out,int) and not isinstance(out,bool) and 0 <= inp <= MAX and 0 <= out <= MAX and inp <= MAX-out: print(inp+out)
PY
  )"
  is_int64_nonnegative "$tokens" || return 0
  record_token_value "$tokens" "$role" "$step_n"
  return 0
}

CLAUDE_BIN=""
resolve_claude_bin() {
  [[ -n "$CLAUDE_BIN" ]] && return 0
  local explicit="${ORCH_CLAUDE_BIN:-}" candidate resolved help flag seen="" supported
  local -a candidates=()
  if [[ -n "$explicit" ]]; then
    [[ "$explicit" == /* ]] || die "ORCH_CLAUDE_BIN must be an absolute path"
    candidates+=("$explicit")
  else
    candidates+=("$HOME/.local/bin/claude")
    candidate="$(command -v claude 2>/dev/null || true)"
    [[ -z "$candidate" ]] || candidates+=("$candidate")
    candidates+=("$HOME/bin/claude" "/opt/homebrew/bin/claude" "/usr/local/bin/claude")
  fi
  for candidate in "${candidates[@]}"; do
    [[ -x "$candidate" ]] || continue
    resolved="$(cd "$(dirname "$candidate")" && pwd -P)/$(basename "$candidate")"
    [[ "|$seen|" != *"|$resolved|"* ]] || continue
    seen="${seen:+$seen|}$resolved"
    help="$("$resolved" --help 2>/dev/null || true)"
    [[ -n "$help" ]] || continue
    supported=1
    for flag in --safe-mode --permission-mode --tools --no-session-persistence --model --fallback-model --effort --output-format --json-schema --max-budget-usd; do
      if [[ "$help" != *"$flag"* ]]; then
        supported=0
        break
      fi
    done
    [[ "$supported" == "1" ]] || continue
    CLAUDE_BIN="$resolved"
    return 0
  done
  die "no Claude Code CLI supports the required safe review flags"
}

claude_auth_mode() {
  local helper mode
  helper="$(dirname "$SELF")/claude_review.py"
  [[ -f "$helper" ]] || die "Claude review helper not found: $helper"
  if ! mode="$("$CLAUDE_BIN" auth status --json | "$VERIFY_PYTHON" "$helper" auth-mode)"; then
    return 1
  fi
  [[ "$mode" == "subscription" || "$mode" == "metered" ]] || return 1
  printf '%s\n' "$mode"
}

effective_claude_auth_mode() {
  local mode
  mode="$(claude_auth_mode)" || return 1
  if [[ "$mode" == "subscription" && (
    -n "${ANTHROPIC_API_KEY:-}" || -n "${ANTHROPIC_AUTH_TOKEN:-}" ||
    -n "${CLAUDE_CODE_USE_BEDROCK:-}" || -n "${CLAUDE_CODE_USE_VERTEX:-}" ||
    -n "${CLAUDE_CODE_USE_FOUNDRY:-}"
  ) ]]; then
    mode="metered"
  fi
  printf '%s\n' "$mode"
}

run_claude_once() { # <prompt> <output> <model> <cli-fallback:0|1> <auth-mode> <step> <direct-fallback:0|1> <role>
  local prompt_file="$1" out_file="$2" model="$3" cli_fallback="$4" auth_mode="$5" step_n="$6" direct_fallback="$7"
  local role="$8" helper result_json log cpid worker_start worker_pgid size last_size=-1 idle=0 usage_tokens="" schema
  local kill_after="${ORCH_STALL_KILL:-300}" hung=0 rc=0 parse_rc=0 metadata="" budget="${ORCH_CLAUDE_MAX_BUDGET_USD:-}"
  local -a cmd parse
  helper="$(dirname "$SELF")/claude_review.py"
  schema="$("$VERIFY_PYTHON" "$helper" schema)" || die "cannot load Claude review schema"
  cmd=("$CLAUDE_BIN" -p --safe-mode --model "$model" --permission-mode plan --tools ""
    --no-session-persistence --effort max --output-format json --json-schema "$schema")
  [[ "$cli_fallback" == "1" ]] && cmd+=(--fallback-model opus)
  [[ "$auth_mode" == "subscription" ]] || budget="${budget:-2}"
  if [[ -n "$budget" ]]; then
    "$VERIFY_PYTHON" -c 'from decimal import Decimal; import sys; assert Decimal(sys.argv[1]) > 0' "$budget" 2>/dev/null || \
      die "ORCH_CLAUDE_MAX_BUDGET_USD must be a positive number"
    cmd+=(--max-budget-usd "$budget")
  fi
  result_json="$(mktemp -t orch-claude-result-XXXX).json"
  log="$(mktemp -t orch-claude-log-XXXX).log"
  [[ -n "$step_n" ]] && emit metric --id "$RUN_ID" --key log --value "$log"
  before_model_call "$role" || return $?
  "${cmd[@]}" < "$prompt_file" >"$result_json" 2>"$log" &
  cpid=$!
  worker_start="$(proc_start "$cpid" || true)"
  worker_pgid="$(proc_pgid "$cpid" || true)"
  if [[ -n "$worker_start" && "$worker_pgid" =~ ^[0-9]+$ ]]; then
    emit worker --id "$RUN_ID" --pid "$cpid" --pid-start "$worker_start" --pgid "$worker_pgid" --cwd "$(pwd -P)"
  fi
  while kill -0 "$cpid" 2>/dev/null; do
    sleep 1
    size="$(( $(wc -c <"$log" 2>/dev/null || echo 0) + $(wc -c <"$result_json" 2>/dev/null || echo 0) ))"
    if [[ "$size" != "$last_size" ]]; then
      last_size="$size"; idle=0; emit heartbeat --id "$RUN_ID" --pid "$$"
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
  if [[ "$hung" == "1" ]]; then
    rm -f "$result_json"
    echo "  Claude produced no output for ${kill_after}s (log: $log)" >&2
    return 124
  fi
  if wait "$cpid"; then rc=0; else rc=$?; fi
  usage_tokens="$("$VERIFY_PYTHON" "$helper" extract-usage --input "$result_json" 2>/dev/null || true)"
  [[ -z "$usage_tokens" ]] || record_token_value "$usage_tokens" "$role" "$step_n"
  parse=("$VERIFY_PYTHON" "$helper" extract-result --input "$result_json" --output "$out_file" --require-model-metadata --require-structured)
  [[ "$cli_fallback" == "1" ]] && parse+=(--retry-on-unavailable)
  [[ "$direct_fallback" == "1" ]] && parse+=(--require-model opus)
  if metadata="$("${parse[@]}" 2>>"$log")"; then
    parse_rc=0
  else
    parse_rc=$?
  fi
  rm -f "$result_json"
  if [[ "$parse_rc" -eq 0 ]]; then
    emit metric --id "$RUN_ID" --key claude.result --value "$metadata"
    return 0
  fi
  [[ "$parse_rc" -eq 10 ]] && return 10
  echo "  Claude review failed (cli=$rc, contract=$parse_rc, log: $log)" >&2
  return 1
}

run_claude_review() { # <prompt> <output> <model> <step> <role>
  local prompt_file="$1" out_file="$2" model="$3" step_n="$4" role="$5" auth_mode fallback_auth rc cli_fallback=0
  resolve_claude_bin
  auth_mode="$(effective_claude_auth_mode)" || die "Claude authentication preflight failed"
  emit metric --id "$RUN_ID" --key claude.auth --value "$auth_mode"
  [[ "$model" == "fable" ]] && cli_fallback=1
  if run_claude_once "$prompt_file" "$out_file" "$model" "$cli_fallback" "$auth_mode" "$step_n" 0 "$role"; then
    return 0
  else
    rc=$?
  fi
  if [[ "$rc" -eq 10 && "$model" == "fable" ]]; then
    fallback_auth="$(effective_claude_auth_mode)" || die "Claude fallback authentication preflight failed"
    [[ "$fallback_auth" == "$auth_mode" ]] || die "Claude authentication mode changed before fallback"
    emit metric --id "$RUN_ID" --key claude.fallback --value "fable-unavailable:direct-opus"
    run_claude_once "$prompt_file" "$out_file" opus 0 "$auth_mode" "$step_n" 1 "$role"
    return
  fi
  return "$rc"
}

codex_run() { # <prompt-file> <out-file> <sandbox> <effort|""> <step-n> <role>
  local prompt_file="$1" out_file="$2" sandbox="$3" effort="$4" step_n="$5" role="$6"
  local attempt=1 max="${ORCH_MAX_RETRY:-2}" kill_after="${ORCH_STALL_KILL:-300}"
  resolve_override "$role" "$effort"
  local -a execution=(execution --id "$RUN_ID" --role "$role" --provider "$OVERRIDE_PROVIDER"
    --source "$OVERRIDE_SOURCE")
  [[ -n "$OVERRIDE_MODEL" ]] && execution+=(--model "$OVERRIDE_MODEL")
  [[ -n "$OVERRIDE_EFFORT" ]] && execution+=(--effort "$OVERRIDE_EFFORT")
  [[ -n "$OVERRIDE_ID" ]] && execution+=(--override-id "$OVERRIDE_ID")
  [[ -n "$OVERRIDE_SET_AT" ]] && execution+=(--set-at "$OVERRIDE_SET_AT")
  [[ -n "$OVERRIDE_EXPIRES_AT" ]] && execution+=(--expires-at "$OVERRIDE_EXPIRES_AT")
  emit "${execution[@]}"
  emit metric --id "$RUN_ID" --key "model.$role" \
    --value "$OVERRIDE_PROVIDER:${OVERRIDE_MODEL:-configured}:${OVERRIDE_EFFORT:-configured}"
  local -a cmd=()
  if [[ "$OVERRIDE_PROVIDER" == "claude" ]]; then
    [[ "$role" == "critique" && -n "$OVERRIDE_MODEL" ]] || die "invalid Claude override for $role"
    run_claude_review "$prompt_file" "$out_file" "$OVERRIDE_MODEL" "$step_n" "$role"
    return
  fi
  cmd=(codex exec --json -s "$sandbox" -c approval_policy=never)
  if [[ -n "$OVERRIDE_MODEL" ]]; then
    cmd+=(-m "$OVERRIDE_MODEL")
  elif [[ "$OVERRIDE_SOURCE" != "override" && "$role" == "implement" ]]; then
    cmd+=(-m "$EXEC_MODEL")
  fi
  [[ -n "$OVERRIDE_EFFORT" ]] && cmd+=(-c "model_reasoning_effort=$OVERRIDE_EFFORT")
  cmd+=(-o "$out_file" -)
  while :; do
    local log cpid last_size=-1 idle=0 hung=0 rc=0 size worker_start worker_pgid last_act_t=0 act
    # Durable per-step log under the run's artifact dir (survives reboot; feeds the
    # dashboard's step 1-7 viewer). Falls back to TMPDIR only if the dir is unavailable.
    if [[ -n "${ARTIFACT_DIR:-}" ]] && mkdir -p "$ARTIFACT_DIR" 2>/dev/null; then
      log="$ARTIFACT_DIR/step-${step_n:-0}-${role:-codex}.log"
      : > "$log"
    else
      log="$(mktemp -t orch-clog-XXXX).log"
    fi
    [[ -n "$step_n" ]] && emit metric --id "$RUN_ID" --key log --value "$log"
    [[ -n "$step_n" ]] && emit step --id "$RUN_ID" --n "$step_n" --log "$log"
    before_model_call "$role" || return $?
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
      capture_tokens "$log" "$role" "$step_n"
      if [[ "$rc" -eq 0 ]]; then return 0; fi
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
  local -a cmd=(codex exec resume --json -c approval_policy=never
    -c "model_reasoning_effort=$EXEC_EFFORT" -o "$out_file" "$session" -)
  log="$(mktemp -t orch-resume-XXXX).log"
  before_model_call repair || return $?
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
  capture_tokens "$log" repair 3
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
  codex_run "$CPROMPT" "$CRIT" read-only "" 2 critique || die "critique step failed (see log above)"
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
  codex_run "$IPROMPT" "$IMPL" "$SANDBOX" "$EXEC_EFFORT" 3 implement || die "implement step failed"
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
  # An approval-only response is a valid gate even when Codex has not changed files.
  # Apply the empty-diff guard only to ordinary implementation responses.
  if [[ -z "$APPROVAL_REQUEST" ]]; then
    ALREADY_AHEAD="$(git rev-list --count "origin/$BASE..HEAD" 2>/dev/null || echo 0)"
    [[ "$DEDICATED_WORKTREE" != "1" || ( "$RESUME" == "1" && "$ALREADY_AHEAD" -ge 1 ) ]] || \
      die "Codex changed nothing in the worktree (see $IMPL) — aborting."
  fi
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
