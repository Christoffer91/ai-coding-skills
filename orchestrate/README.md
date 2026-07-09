# Orchestrate — dual-brain plan → execute → review → ship loop

A Claude Code skill that takes a change from idea to (optionally) deployed across **two models**:

- **Claude** (a strong planning/reviewing model, e.g. Fable or Opus) plans the change and reviews the PR — the taste/judgment half.
- **OpenAI Codex CLI (`gpt-5.6-sol`)** critiques the plan, writes the code, opens the PR, and applies review edits — the execution half.

Keep expensive judgment work on Claude; hand mechanical, well-spec'd execution to Codex (which runs on your ChatGPT/Codex subscription). Default is hands-off; deploy is human-gated.

## Requirements
- **Claude Code** CLI — the `/orchestrate` skill runs here.
- **OpenAI Codex CLI**, installed and logged in (`codex login`) → provides `gpt-5.6-sol`. Check: `codex --version`. Set `model = "gpt-5.6-sol"` in `~/.codex/config.toml`.
- **GitHub CLI `gh`**, authed with `repo` + `workflow` scopes (`gh auth status`).
- **git**, and a repo with a remote.

No API keys needed if Codex uses ChatGPT OAuth and `gh` uses its keyring token.

## Install
```bash
./install.sh
```
This copies the skill into `~/.claude/skills/orchestrate/` and marks the driver executable. Then, optionally (recommended), paste the two contract snippets so every session defaults to the split:
- `contract/CLAUDE.snippet.md` → append to `~/.claude/CLAUDE.md`
- `contract/AGENTS.snippet.md` → append to `~/.codex/AGENTS.md`

## Use
- In Claude Code: **`/orchestrate <topic>`** (have a `PLAN-<topic>.md` spec ready).
- Headless Codex leg only: `scripts/orchestrate.sh <topic> PLAN.md`
- Preview without running anything: `ORCH_DRYRUN=1 scripts/orchestrate.sh <topic> PLAN.md`

Per-repo config (deploy target, effort, caps): copy `contract/orchestrate.toml.example` to `<repo>/.ai/orchestrate.toml`.

## The loop
1. **Plan** (Claude) → 2. **Critique** (Codex) → 3. **Implement** (Codex, sandboxed) → 4. **Open PR** (driver) → 5. **Review** (Claude) → 6. **Apply edits** (Codex) → 7. **Deploy** (human-gated by default).

## Safety
- Branch-per-task; PR always; never direct-push to `main`.
- Codex runs sandboxed (`workspace-write`, no network): it commits; the driver pushes/PRs.
- **Deploy is human-gated by default.** Auto-deploy requires a per-repo `deploy_authorized = true` that **you** set — an agent never self-authorizes a production deploy. See `skills/orchestrate/references/auto-deploy-safety.md`.
- The review↔fix loop is capped (default 3) to prevent runaways.

## Layout
```
skills/orchestrate/SKILL.md              the skill (the conductor)
skills/orchestrate/references/           auto-deploy-safety · loop-mechanics · desktop-mcp-bridge
scripts/orchestrate.sh                   headless Codex-leg driver
contract/CLAUDE.snippet.md               paste into your ~/.claude/CLAUDE.md
contract/AGENTS.snippet.md               paste into your ~/.codex/AGENTS.md
contract/orchestrate.toml.example        per-repo config template
install.sh                               installer
```

## Notes
- Reasoning effort: critique + PR review run at your Codex config default (judgment); implement + fix run at `medium` (mechanical). Tune with `exec_effort` / `ORCH_EXEC_EFFORT`.
- For Claude Desktop, bridge Codex in via `codex mcp-server` — see `skills/orchestrate/references/desktop-mcp-bridge.md`.
- Not for trivial one-file edits — it's built for real, well-spec'd changes worth handing to gpt-5.6-sol.

Licensed for internal reuse; adapt freely.
