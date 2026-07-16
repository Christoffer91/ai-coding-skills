# Chief of Staff — one chat runs the whole session

Turns a single Claude Code chat into the session's chief of staff: it decomposes a broad goal into
2–6 workstreams, delegates them to **parallel background subagents**, re-commands workers mid-flight
(SendMessage), routes anything that becomes real implementation into the sibling
[orchestrate](../orchestrate/) loop, and delivers ONE synthesized report.

**Honest boundary:** Claude Code cannot create new top-level chats or command other human chat
sessions. This skill orchestrates *within the current session* — subagents live and die with the
chat. It is deliberately not a persistent cross-session conductor.

## Layout

```text
claude/skills/chief-of-staff/SKILL.md    Claude Code entrypoint (/chief-of-staff)
```

Claude-only: the pattern is built on Claude Code's subagent primitives (parallel background Agent
calls, SendMessage re-command), which have no Codex CLI equivalent.

## Install

```bash
cp -R claude/skills/chief-of-staff ~/.claude/skills/chief-of-staff
```
Or via the marketplace: `/plugin install chief-of-staff@ai-coding-skills`.

## Notes

- Fan-out is read-only by default; write-work routes to the orchestrate loop (worktree isolation).
- Dashboard telemetry (`orchestrate-status …`) comes from the sibling orchestrate package; without
  it those calls no-op and the skill still works.
- Guardrails against "council theater": if one careful pass settles it, no staff is spawned.

Licensed for internal reuse; adapt freely.
