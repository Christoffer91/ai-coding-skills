# Pipeline — one entrypoint, coverage matrix, verified output

A pair of skills (one per tool) that enforce a standard delivery pipeline for non-trivial work: continuity tracking, a coverage matrix (security / risk / review / tests / docs), adaptive routing, verification gates, and PR-ready output. Non-trivial implementation routes into the sibling [orchestrate](../orchestrate/) loop; trivial or bounded work stays on a cheap direct path.

## Layout

```text
claude/skills/pipeline/SKILL.md   Claude Code entrypoint (/pipeline)
codex/skills/pipeline/            Codex CLI entrypoint ($pipeline): skill, references, agent config
```

## Install

No installer — copy each side into the matching skills directory:

```bash
cp -R claude/skills/pipeline  ~/.claude/skills/pipeline
cp -R codex/skills/pipeline   ~/.codex/skills/pipeline
```

## Notes

- Both sides reference companion skills (`risk-assess`, `security-audit`, `prepare-pr`, `orchestrate`, …). Missing companions degrade gracefully: treat those rows of the coverage matrix as manual steps.
- The Codex side's `orchestrate` skill validator expects `pipeline` installed as a sibling in `~/.codex/skills` — the copy commands above satisfy that.
- Model names in the routing tables are examples; tune them to the models and prices you actually have.

Licensed for internal reuse; adapt freely.
