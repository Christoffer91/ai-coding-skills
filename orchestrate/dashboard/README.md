# orchestrate dashboard

One local page for **every** `/orchestrate` run on this machine — live status, the 7-step pipeline, **click-to-answer gates**, and a copy-review-command action on handoffs. No dependencies (Python 3 stdlib); binds to `127.0.0.1` only.

## Run it
```bash
./orchestrate-dashboard            # → http://localhost:4600
./orchestrate-dashboard --port 8080
```
Leave it running in a tab; it auto-refreshes every 4s. (Tip: symlink both scripts onto your PATH, e.g. `ln -s "$PWD/orchestrate-dashboard" ~/.local/bin/`.)

## How it works
- Each run's status lives in `~/.orchestrate/runs/<id>.json`, written by **`orchestrate-status`** (below).
- The dashboard reads them all and serves the aggregate view + `/api/runs` (JSON, polled by the page).
- Clicking a gate option `POST`s `/api/answer` → writes `~/.orchestrate/answers/<id>.json`, which the run's `orchestrate-status wait` picks up to unblock.
- Optional Codex session liveness lives separately in `~/.orchestrate/liveness/`; it is never allowed to
  rewrite a run record or extend terminal-history retention.

## Emitting status — `orchestrate-status`
The `/orchestrate` skill and `scripts/orchestrate.sh` call these at each step (they no-op if the tool isn't installed, so status is optional telemetry):
```bash
orchestrate-status start  --id <id> --repo R --topic T --title "…" --branch B [--planner "…"] [--executor "…"] [--resume-command "…"] [--codex-session /abs/rollout.jsonl --codex-turn <turn-id>]
orchestrate-status step   --id <id> --n 1..7 --state active|done|fail [--note "…"] [--codex-session /abs/rollout.jsonl --codex-turn <turn-id>]
orchestrate-status pr     --id <id> --number N --url U [--state OPEN]
orchestrate-status metric --id <id> --key tests --value "12/12"
orchestrate-status gate   --id <id> --question "…" --option "Merge & deploy:primary" --option "Leave PR open"
choice=$(orchestrate-status wait --id <id> --timeout 0)   # blocks until you click; prints your choice
orchestrate-status done   --id <id>
orchestrate-status resume --id <id> --reason "explicit user resume"
orchestrate-status resume-command --id <id> (--command "…" | --clear)
orchestrate-status rm     --id <id>
```
`<id>` is any stable slug for the run (e.g. `<repo>-<topic>`).

`gate`, `fail`, and `handoff` each send one notification. Set `ORCH_NOTIFY_CMD` to an executable path, or set repo-local `notify_cmd` in `.ai/orchestrate.toml` to a quoted path or argv array. The message is appended as one argument and the hook is killed after 10 seconds; no shell evaluates the config. On macOS, Notification Center is the desktop fallback when no hook is configured. Use a phone-capable hook or in-session `PushNotification` for Remote Control.

## Codex session liveness — `orchestrate-codex-sidecar`

This optional, best-effort adapter keeps a **no-PID Codex run** live while its exact bound session is
producing new rollout events. It is deliberately not a lifecycle engine: it never calls
`orchestrate-status heartbeat`, never modifies steps/status/`updatedAt`, and never infers `done`
from `task_complete` or any other transcript event.

Use it only when the host can provide both the absolute rollout file and the current Codex
`turn_id`; do not guess a most-recent session. Record the pair when the run starts, then launch the
sidecar as an optional background process. The initial turn is immutable correlation metadata, not
a per-event filter: later recognized events in the same rollout count across turn boundaries, and
turnless `response_item` events count too.

```bash
orchestrate-status start --id "$RUN_ID" --repo "$REPO" --topic "$TOPIC" --title "$TITLE" \
  --branch "$BRANCH" --codex-session "$ROLLOUT" --codex-turn "$TURN_ID"
nohup orchestrate-codex-sidecar --id "$RUN_ID" --session "$ROLLOUT" --turn "$TURN_ID" \
  >/dev/null 2>&1 &
```

The run JSON and `/api/runs` receive only SHA-256-style opaque references, never the rollout path,
turn id, event kind, transcript text, tool output, or parser errors. The sidecar starts at EOF, uses
a bounded byte parser, ignores malformed/oversized/partial lines, and writes only a
generation-bound lease. It exits and removes its lease and lock on idle, SIGTERM, an
inactive/removed run, run-generation mismatch, or missing/replaced/truncated rollout. A duplicate sidecar
for the same run generation exits without taking over the lease.

If the host cannot provide the exact pair, skip the sidecar silently; the dashboard's honest
`quiet` state remains the correct signal. A quick manual smoke is to launch it against a real,
currently bound goal and confirm that its localhost card remains `running` while the session emits
activity, then becomes `quiet` after liveness stops. The sidecar does not make a stalled worker
restartable and does not alter authoritative run retention.

## Interactive gates (the couch-approval loop)
At a gate (e.g. deploy), the run emits `gate …` then blocks on `wait`. The dashboard shows the question with buttons under **Needs you**; your click sends the choice back and the run continues. Same mechanism works for any decision, not just deploy.

## Files
- `orchestrate-dashboard` — the server (stdlib http.server)
- `orchestrate-status` — the status emitter / gate-answer waiter
- `orchestrate-codex-sidecar` — optional, isolated Codex rollout liveness lease writer
- `liveness.py` — shared opaque-binding and lease validation helpers
- `dashboard.html` — the page the server serves (served as-is; edit to restyle)

## Always-on (macOS launchd)
The dashboard/watchdog die with the session that started them. For an always-on setup that
survives reboots, run the installer YOURSELF (it installs login agents — deliberate persistence):
```bash
bash launchd/install-launchd.sh     # installs + loads com.orchestrate.{dashboard,watchdog}
```
Logs land in `~/.orchestrate/logs/*-launchd.log`; uninstall command is printed by the installer.

## Keeping runs on track — orchestrate-watchdog
`./orchestrate-watchdog` (run alongside the dashboard) polls the runs and, for the
cases the driver's own auto-recovery can't reach (its whole process died, or an
in-session run stalled), reaps any orphaned `codex` in the run's cwd and flags the
run `needsRestart` (logged to `~/.orchestrate/watchdog.log`). It detects + reaps +
escalates; it does NOT redispatch — use the dashboard's ↻ Restart button. Flags: `--poll 30 --grace 180 --once`.

## Naming — match your Claude chat
The card shows the run's **title**. Set it to the same name you use for the work in
your Claude chat so the dashboard lines up with your tabs:
- driver:     `ORCH_TITLE="CoWriter loop" orchestrate.sh cowriter`
- in-session: `orchestrate-status start --title "CoWriter loop" …`

## Terminal view — orchestrate-watch
`./orchestrate-watch` renders the same runs as the dashboard in your terminal:
current step + live activity note, colored liveness, and "changed Xs ago" per run.
Flags: `--interval 2` (refresh), `--once` (print and exit), `--all` (include old
done runs). Ctrl-C quits.

## Mobile access (Tailscale)
The dashboard binds to 127.0.0.1 only — expose it to YOUR devices (never the
public internet) with Tailscale Serve:
1. Install Tailscale on the machine and phone; log both into the same tailnet.
2. One-time on the tailnet: enable **HTTPS certificates** (Serve prompts with a
   link). Leave **Funnel OFF**. Tailnet devices are trusted operators: device
   identity is the access boundary for actions such as gates and restarts.
3. `tailscale serve --bg http://127.0.0.1:4600` → prints your private
   `https://<machine>.<tailnet>.ts.net` URL (TLS automatic, tailnet-only).
4. Phone: open the URL in the browser → Share → Add to Home Screen. The
   dashboard becomes an app: gates, model overrides, /watch and /console all work.
5. Disable anytime: `tailscale serve --https=443 off`.
Pairs with the ntfy notify hook: the phone gets pinged at gates, the home-screen
app is where you answer.

Mutating browser requests with `Sec-Fetch-Site: cross-site` are rejected. Normal
same-origin navigation, `Sec-Fetch-Site: none`, and headerless CLI/curl requests
remain supported. This is CSRF hardening, not a replacement for the tailnet trust
boundary; never enable Funnel for this dashboard.

## Run lifecycle extras
`orchestrate-status pause|resume --reason|cancel [--reason]|checkpoint|execution --id <id>` — lifecycle
bookkeeping (`pause` is inactive and requires explicit `resume`; `step` never resumes it implicitly), cancel with a recorded reason, persist a named checkpoint, and update
execution state for approval flows (used by the driver's approval gates and resume paths).
