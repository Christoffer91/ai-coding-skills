# orchestrate dashboard

One local page for **every** `/orchestrate` run on this machine — live status, the 7-step pipeline, and **click-to-answer gates** (approve a deploy/decision from the browser). No dependencies (Python 3 stdlib); binds to `127.0.0.1` only.

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

## Emitting status — `orchestrate-status`
The `/orchestrate` skill and `scripts/orchestrate.sh` call these at each step (they no-op if the tool isn't installed, so status is optional telemetry):
```bash
orchestrate-status start  --id <id> --repo R --topic T --title "…" --branch B [--planner "…"] [--executor "…"]
orchestrate-status step   --id <id> --n 1..7 --state active|done|fail [--note "…"]
orchestrate-status pr     --id <id> --number N --url U [--state OPEN]
orchestrate-status metric --id <id> --key tests --value "12/12"
orchestrate-status gate   --id <id> --question "…" --option "Merge & deploy:primary" --option "Leave PR open"
choice=$(orchestrate-status wait --id <id> --timeout 0)   # blocks until you click; prints your choice
orchestrate-status done   --id <id>
orchestrate-status rm     --id <id>
```
`<id>` is any stable slug for the run (e.g. `<repo>-<topic>`).

## Interactive gates (the couch-approval loop)
At a gate (e.g. deploy), the run emits `gate …` then blocks on `wait`. The dashboard shows the question with buttons under **Needs you**; your click sends the choice back and the run continues. Same mechanism works for any decision, not just deploy.

## Files
- `orchestrate-dashboard` — the server (stdlib http.server)
- `orchestrate-status` — the status emitter / gate-answer waiter
- `dashboard.html` — the page the server serves (served as-is; edit to restyle)

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
