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
- Python 3 standard library for the dashboard/status/watchdog tools.

No API keys are needed when Codex uses ChatGPT OAuth and `gh` uses its keyring token.

## Install

```bash
./install.sh
# Also link the driver/dashboard/status/watchdog into ~/.local/bin:
./install.sh --link-bin
```

The installer backs up an existing skill, installs the skill plus dashboard, checks required CLIs, and prints the dashboard/watchdog commands. The optional contract snippets remain available for global model-role defaults:

- `contract/CLAUDE.snippet.md` → append to `~/.claude/CLAUDE.md`
- `contract/AGENTS.snippet.md` → append to `~/.codex/AGENTS.md`

## Use

- In Claude Code: `/orchestrate <topic>` with a `PLAN-<topic>.md` spec.
- Review a handoff: `/orchestrate review <topic>`; the dashboard handoff card can copy this command.
- Headless Codex leg: `scripts/orchestrate.sh <topic> PLAN.md`.
- Resume an approval timeout from its recorded worktree: `scripts/orchestrate.sh --resume --timeout 0 <topic> PLAN.md`.
- Preview without writes: `ORCH_DRYRUN=1 scripts/orchestrate.sh <topic> PLAN.md`.

Start `dashboard/orchestrate-dashboard` for local status and `dashboard/orchestrate-watchdog` for stale-worker recovery. The dashboard binds to `127.0.0.1` and reads run state from `~/.orchestrate/runs`.

For phone-capable driver notifications, set `ORCH_NOTIFY_CMD=/absolute/path/to/hook` or repo-local `.ai/orchestrate.toml` `notify_cmd` to a quoted path/argv array. The hook receives the message as one argument and is executed directly, never through a shell. macOS Notification Center is only a desktop fallback; Remote Control gates use `PushNotification` plus `AskUserQuestion` in-session.

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
skills/orchestrate/SKILL.md              conductor and validated review entry
skills/orchestrate/references/           deploy safety, loop mechanics, Desktop bridge
scripts/orchestrate.sh                   headless Codex-leg driver
dashboard/orchestrate-dashboard          localhost status server/UI
dashboard/orchestrate-status             state emitter, gates, notifier hook
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
