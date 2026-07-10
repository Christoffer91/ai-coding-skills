<!--
Paste this section into your own ~/.claude/CLAUDE.md so every Claude Code
session defaults to the dual-brain split. Optional — the /orchestrate skill
also works when invoked explicitly. Tune the table to your own models/judgment.
-->

## Model roles & orchestration (dual-brain: Claude plans, Codex/GPT executes)
Default operating model for coding work. **Claude** is the planner + PR reviewer (taste/judgment). **OpenAI Codex CLI (`gpt-5.6-sol`)** is the plan-critic + executor + PR author (cheap, well-spec'd execution, runs on your ChatGPT/Codex plan).

**Role table** (illustrative — adjust to your models and what you pay; higher = better):

| model | cost | intelligence | taste | default role |
|---|---|---|---|---|
| gpt-5.6-sol (via Codex CLI) | low | high | med | execute / code / verify / bulk |
| a strong Claude planner (e.g. Fable or Opus) | med | high | high | plan + review PRs |
| a top-tier Claude model (e.g. Fable) | high | top | top | premium planner/reviewer (opt-in) |
| a small Claude model (e.g. Sonnet) | low | med | good | thin wrapper for `codex exec` calls in workflows |

**How to apply:**
- Defaults, not limits — if a cheaper model's output is weak, rerun with a stronger one. Judge the output, not the price.
- When axes conflict for anything that ships: intelligence > taste > cost.
- Bulk/mechanical work → Codex/gpt-5.6-sol. User-facing work (UI, copy, API design) → your higher-taste Claude model. Reviews → a strong Claude model, optionally Codex as a second independent lens.

**Mechanics:**
- gpt-5.6-sol is reachable only through the Codex CLI — `codex exec` (headless) and `codex review`. Set your default in `~/.codex/config.toml` (`model = "gpt-5.6-sol"`).
- Inside a Claude Agent/Workflow (whose `model` param takes Claude models only), reach gpt-5.6-sol by spawning a small Claude wrapper agent that runs `codex exec` via Bash and returns the result.
- Cross-tool handoffs use `HANDOFF-<TARGET>-<TOPIC>.md` files. Codex can also be exposed to Claude Desktop as a tool via `codex mcp-server`.

**The default loop** (run end-to-end with `/orchestrate`; default hands-off, `--supervised` to gate each step):
1. Claude plans → 2. gpt-5.6-sol critiques the plan (`codex exec -s read-only`) → 3. gpt-5.6-sol codes on a task branch (`codex exec -s workspace-write`) → 4. gpt-5.6-sol/driver opens PR (`gh pr create`) → 5. Claude reviews the PR (optionally `codex review` as a 2nd lens) → 6. gpt-5.6-sol applies edits (cap ~3 iterations) → 7. deploy: human-gated unless the repo is explicitly authorized (see the skill's `auto-deploy-safety.md`).

Standing rule: when the next phase is execution on a well-spec'd plan, hand to Codex; when it's judgment/planning/PR-review, keep it in Claude.

**Spec-driven planning (always):** implementation work starts from a `PLAN-<topic>.md` per the orchestrate spec template (numbered fixes with file paths, runnable acceptance, out-of-scope). Planner: your strongest Claude when available; otherwise draft the spec with gpt-5.6-sol at ultra (`codex exec -s read-only`) and validate it in-session before any execution.
