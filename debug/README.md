# Debug — evidence-driven debugging with a dual-brain council

A pair of debugging skills. The default path is a cheap, systematic single-pass loop (repro →
hypotheses → falsify → minimal fix → verify). Hard bugs escalate to **council mode**: Claude and
the OpenAI Codex CLI research the same failure independently (no shared hypotheses, so no
anchoring), Claude synthesizes and falsifies, and if 2–3 fixes remain plausible they race in
disposable git worktrees — the winner is picked on test outcome, then minimality.

Token-conscious by design: an escalation ladder (quick loop → one cheap recon leg → stronger
legs → worktree race) where each rung is climbed only after the previous one failed, bounded
briefs/answers per leg, and a mandatory token-usage line in the final report.

## Layout

```text
claude/skills/debug/SKILL.md                   Claude Code entrypoint (/debug, /debug deep)
codex/skills/systematic-debugging/SKILL.md     Codex CLI single-pass lane ($systematic-debugging)
```

## Install

```bash
cp -R claude/skills/debug                ~/.claude/skills/debug
cp -R codex/skills/systematic-debugging  ~/.codex/skills/systematic-debugging
```

## Requirements and notes

- Council mode's GPT legs need the OpenAI Codex CLI (`codex login`); without it, `/debug` still
  works as the single-pass loop with Claude-only subagent legs.
- The optional dashboard telemetry (`orchestrate-status …`) comes from the sibling
  [orchestrate](../orchestrate/) package; without it those calls no-op.
- Model names in the ladder are examples — substitute the cheap/strong models you actually have.

Licensed for internal reuse; adapt freely.
