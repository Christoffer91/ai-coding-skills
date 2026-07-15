# Critique — fair-but-rigorous pushback before you commit

A critical-friend skill: steelman the idea, challenge it, give a calibrated verdict — not a
negativity generator. Use it before spending time building, to pressure-test a plan/prompt/
architecture, or as a pre-mortem. It says "solid" plainly when the idea is already good.

Four modes: `rubber-duck` (help you think), `critique` (default), `hard-challenge` (pre-mortem /
failure modes), `decision` (compare options). Depth scales with stakes — solo by default, a
**council** of parallel subagent lenses for wide calls, and an optional independent **second-model
opinion** (via the OpenAI Codex CLI) so a high-stakes verdict isn't single-model.

## Layout

```text
claude/skills/critique/SKILL.md    Claude Code entrypoint (/critique)
```

There is no Codex-side twin in this package: the Codex CLI already ships an equivalent `critique`
skill. This is the Claude-tailored version (Claude Code primitives: subagent fan-out, Codex second
lens, handoffs to the Claude review skills).

## Install

```bash
cp -R claude/skills/critique ~/.claude/skills/critique
```
Or via the marketplace: `/plugin install critique@ai-coding-skills`.

## Notes

- Read-only by design: it reasons, investigates, and (optionally) calls a read-only second model —
  it never edits, commits, or deploys.
- Handoffs reference sibling skills (`architecture-review`, `risk-assess`, `security-audit`,
  `deep-research`, `code-review`); missing siblings just become manual next steps.
- The second-model lens assumes the OpenAI Codex CLI is installed and logged in; it degrades to a
  solo critique when absent.

Licensed for internal reuse; adapt freely.
