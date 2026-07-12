---
name: debug
description: 'Use when a test fails locally or in CI, behavior is intermittent/flaky, a stack trace or error message has no clear root cause, or the system "doesn''t work". Systematic, evidence-driven diagnosis that minimizes change scope; escalates hard bugs to a dual-brain council (parallel Claude + GPT research, candidate fixes raced in worktrees). Not for running final checks on a likely-done change (use verify) or planning what tests to write (use test-coverage). Keywords: bug, debug, repro, flaky, stack trace, CI failure, test failure, regression, root cause, council.'
allowed-tools: Read, Glob, Grep, Bash
---

# Systematic Debugging

## Purpose
Debug failures using a repeatable, evidence-driven workflow that minimizes scope and changes.

## When to Use
- A bug with unclear root cause
- Tests fail locally or in CI
- The system "doesn't work"

## When NOT to Use
- Design/architecture task (use `/architecture-review`)
- Just need final checks (use `/verify`)

## Steps

1. **Stabilize the repro** - Minimal steps + expected vs actual
2. **Trim working set** - Smallest set of files that could cause issue
3. **Form hypotheses** - List 2-5 with quick tests to falsify
4. **Collect evidence** - Run smallest relevant command first
5. **Apply minimal fix** - Change as little as possible
6. **Verify** - Re-run failing test, record outcome

## Council mode — dual-brain deep debugging

Escalate to council mode when the quick loop above stalls: the first hypothesis pass is falsified
with no survivor, the bug is flaky/intermittent, it spans domains (build+runtime, client+server),
or the user asks for `/debug deep`. Council mode buys independence — brains research the SAME
failure without seeing each other's guesses — but pay for it per rung. **Climb the ladder only
while the cheaper rung has failed; never start at the top.**

**The escalation ladder (each rung only after the previous one failed):**

| Rung | What | Cost |
|---|---|---|
| 0 | Quick loop above, in-session | ~free |
| 1 | ONE GPT leg (Luna high, read-only) + ONE Explore subagent, in parallel | cheap |
| 2 | + Sol xhigh leg (gnarly logic) and/or web leg (library implicated) | medium |
| 3 | Race 2 (max 3) candidate fixes in disposable worktrees | expensive |

1. **Stabilize the repro first** (steps 1–2 above). No repro → no council; a council without a
   deterministic-enough repro just multiplies noise.
2. **Brief hygiene (this is where tokens go to die):** every leg gets the same self-contained brief —
   repro command, exact error, expected vs actual, ≤10 suspect file paths. Paths and line ranges,
   never whole-file pastes. Require bounded answers: "return ranked hypotheses + evidence pointers,
   ≤300 words, no file dumps." No shared hypotheses between legs before synthesis.
   GPT legs: `codex exec -s read-only -c approval_policy=never` with the brief via stdin redirect.
3. **Synthesize (Claude judges):** merge and dedupe hypotheses, rank by evidence, design one cheap
   falsification test per survivor, and run falsifications in-session — a 2-minute falsification
   beats another model call. If one hypothesis survives, skip rung 3 entirely: fix it directly.
4. **Race candidate fixes** only when falsification cannot separate the top 2–3: one disposable
   `git worktree` per candidate, implemented by Terra (`codex exec -s workspace-write`, one
   candidate per session) or an Opus subagent when Codex quota is empty. Each candidate runs the
   failing test plus the adjacent suite — not the full suite unless the fix is in shared code.
   Never experiment in the user's working tree; never commit from a worktree (the session applies
   the winner); default 2 candidates, hard cap 3.
5. **Verdict and apply:** pick the winner on test outcome first, minimality second. Apply via the
   normal route — directly for a small diff, through `/orchestrate` with a spec when the real fix
   turns out non-trivial. Remove the losing worktrees.

**Token accounting (mandatory in the final answer):** capture each GPT leg's usage from its log —
the last `tokens used` line, same pattern as the orchestrate driver:
`awk 'prev ~ /tokens used/ {s=$0; gsub(/[,[:space:]]/,"",s); if (s ~ /^[0-9]+$/) last=s} {prev=$0} END {print last}' <log>`.
Report per-leg and total in the Debugging Report's `Tokens` line (Claude subagents: report count and
model; exact token counts are not exposed — say "n/a" rather than guessing), and emit
`orchestrate-status metric --id <id> --key tokens.debug --value <total>` so the dashboard shows it.

Emit dashboard telemetry for council runs (`orchestrate-status start --id <repo>-debug-<slug>`,
step notes per rung, ALWAYS a terminal `done`/`fail` — see the orchestrate skill's emit discipline).

## Output Format
```
## Debugging Report
- Repro: [minimal steps]
- Error: [exact message]
- Hypotheses:
  1. [hypothesis] - [how to test]
- Leading theory: [most likely cause]
- Fix: [changes made]
- Verification: `[command]` -> PASS/FAIL
- Tokens: [council only — per leg + total, e.g. "luna-recon 41k · sol-xhigh 118k · terra-fix×2 260k → total 419k · claude subagents: 1 Explore (n/a)"]
```

## Example
```
## Debugging Report
- Repro: `pytest tests/test_auth.py::test_login -x`
- Error: `AssertionError: assert 401 == 200` (login returns 401)
- Hypotheses:
  1. Password hash mismatch - log the stored vs computed hash
  2. Clock skew expires the token immediately - print token `exp` vs `now`
- Leading theory: token `exp` set in the past (hypothesis 2 falsified hash; exp was now-60s)
- Fix: use `utcnow() + timedelta(minutes=15)` instead of `utcnow() - 60`
- Verification: `pytest tests/test_auth.py::test_login -x` -> PASS
```

## Safety Notes
- Ask before destructive commands
- Don't chase symptoms without repro

## Related Skills
- `/verify` - for final pre-PR checks
- `/continuity` - if context seems lost
- `/test-coverage` - if tests are missing
- `/codex` - the GPT research leg in council mode
- `/orchestrate` - applying a non-trivial winning fix as a spec'd loop
