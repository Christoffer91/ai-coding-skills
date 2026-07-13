# Orchestrate — dual-brain plan → execute → review → ship loop

A Claude Code skill that takes a change from idea to an optionally deployed PR across two models:

- **Claude** plans the change and reviews the PR — the taste/judgment half.
- **OpenAI Codex CLI (`gpt-5.6-sol`)** critiques the plan, writes the code, opens the PR, and applies review edits — the execution half.

Keep expensive judgment work on Claude; hand mechanical, well-specified execution to Codex. Default is hands-off; real approval moments and deploy are gated.

## Requirements

- Claude Code CLI.
- OpenAI Codex CLI, installed and logged in (`codex login`).
- GitHub CLI `gh`, authenticated with repo/workflow access.
- Git and a repo with a remote.
- Python 3 for the dashboard/status/watchdog tools; the verify gate selects Python 3.11+ with `tomllib` (or a Python with the `tomli` backport).

No API keys are needed when Codex uses ChatGPT OAuth and `gh` uses its keyring token.

## What do you actually need?

The package is layered — only the skill itself is the product; the rest is opt-in:

1. **The skill** (required): the plan → execute → review loop. Fully functional alone; all
   `orchestrate-status` telemetry calls no-op when the dashboard tools aren't installed.
2. **Dashboard** (optional): a localhost status page with click-to-answer gates. Nice for
   watching multiple runs; nothing depends on it.
3. **Watchdog** (optional, on top of the dashboard): flags dead/stalled runs for one-click
   restart. Skip it unless you run many unattended loops.
4. **launchd always-on** (optional, macOS): keeps dashboard+watchdog running across reboots.
   A separate script you run deliberately (`dashboard/launchd/install-launchd.sh`); nothing
   installs persistence for you.

## Install

Quickest (skill only, via Claude Code's plugin system):

```
/plugin marketplace add Christoffer91/ai-coding-skills
/plugin install orchestrate@ai-coding-skills
```

Full install from a clone (skill + dashboard + driver + Codex-side skill). When run in a
terminal it finishes by ASKING about each optional layer (PATH links, start the dashboard,
launchd always-on) — every question defaults to No, so Enter-Enter-Enter gives you the plain
skill:

```bash
./install.sh
# Also link the driver/dashboard/status/watchdog/Codex-sidecar into ~/.local/bin:
./install.sh --link-bin
```

The installer backs up an existing skill, installs the Claude skill plus dashboard, installs the Codex-side skill into `~/.codex/skills` when a `~/.codex` directory exists (override with `CODEX_SKILLS_DIR`), checks required CLIs, and prints the dashboard/watchdog commands. The optional contract snippets remain available for global model-role defaults:

- `contract/CLAUDE.snippet.md` → append to `~/.claude/CLAUDE.md`
- `contract/AGENTS.snippet.md` → append to `~/.codex/AGENTS.md`

## Use

- In Claude Code: `/orchestrate <topic>` with a `PLAN-<topic>.md` spec.
- Review a handoff: `/orchestrate review <topic>`; the dashboard handoff card can copy this command.
- Headless Codex leg: `scripts/orchestrate.sh <topic> PLAN.md`.
- Resume an approval timeout from its recorded worktree: `scripts/orchestrate.sh --resume --timeout 0 <topic> PLAN.md`.
- Preview without writes: `ORCH_DRYRUN=1 scripts/orchestrate.sh <topic> PLAN.md`.

Start `dashboard/orchestrate-dashboard` for local status and `dashboard/orchestrate-watchdog` for stale-worker recovery. The dashboard binds to `127.0.0.1` and reads run state from `~/.orchestrate/runs`. `dashboard/orchestrate-codex-sidecar` is an optional, generation- and session-bound liveness adapter for a host that can supply an exact Codex rollout path and initial turn id; it writes a separate lease and never changes run status or completion.

For phone-capable driver notifications, set `ORCH_NOTIFY_CMD=/absolute/path/to/hook` or repo-local `.ai/orchestrate.toml` `notify_cmd` to a quoted path/argv array. The hook receives the message as one argument and is executed directly, never through a shell. macOS Notification Center is only a desktop fallback; Remote Control gates use `PushNotification` plus `AskUserQuestion` in-session.

Repo-local `test_cmd`, `build_cmd`, and `eval_cmd` entries add an independent pre-push verify gate. Prefer argv arrays. They execute directly in the task worktree with a per-command `ORCH_VERIFY_TIMEOUT` (default 900 seconds), write logs under `~/.orchestrate/artifacts/<id>/`, and never invoke a shell. Keep `.ai/orchestrate.toml` gitignored, trusted, and secret-free; do not use verification configuration supplied by a PR.

## The loop

1. Plan (Claude) → 2. Critique (Codex) → 3. Implement (Codex, sandboxed) → 4. Open PR (driver) → 5. Review (Claude) → 6. Apply edits (Codex) → 7. Deploy (risk-gated).

## Safety

- Branch-per-task; PR always; never direct-push to `main`.
- Codex runs sandboxed (`workspace-write`, no network); the driver owns push/PR.
- Approval markers block push/PR and persist across timeout/restart without rerunning Codex.
- Auto-deploy requires user-set `deploy_authorized = true`, low risk, green CI, a mergeable PR, and a configured deploy mechanism.
- The review↔fix loop is capped at three iterations by default.

## Layout

```text
claude/skills/orchestrate/SKILL.md       Claude Code conductor and validated review entry
claude/skills/orchestrate/references/    deploy safety, loop mechanics, Desktop bridge
codex/skills/orchestrate/                the Codex CLI side: skill, references, validator
scripts/orchestrate.sh                   headless Codex-leg driver
scripts/orchestrate_verify.py            safe TOML/argv verifier and test-delta classifier
dashboard/orchestrate-dashboard          localhost status server/UI
dashboard/orchestrate-status             state emitter, gates, notifier hook
dashboard/orchestrate-codex-sidecar      optional isolated Codex liveness lease writer
dashboard/liveness.py                    opaque binding and lease helpers
dashboard/orchestrate-watchdog           stale-worker detection/recovery
tests/test_orchestrate_hardening.py       driver/dashboard/watchdog/package tests
contract/                                global snippets and repo config example
install.sh                               installer and optional PATH links
```

## Verify

```bash
bash -n orchestrate/install.sh orchestrate/scripts/orchestrate.sh
python3 -m unittest discover -s orchestrate/tests -v
```

Licensed for internal reuse; adapt freely.
