---
name: systematic-debugging
description: "Use when a bug, test failure, flaky test, local/CI failure, unclear root cause, or repro gap needs evidence-driven debugging: reproduce, isolate, hypothesize, minimal change, and verify. Use instead of loop for single-pass debugging, loop-controller for formal execution loops, verification-before-completion for final checks, and test-coverage for missing test plans. Triggers: test failure, flaky test, fails locally, repro steps, it doesn't work."
allowed-tools: "codebase readFile search usages changes problems todos edit runCommands runTests testFailure"
---
# Systematic Debugging

## SAFETY GATE
- STOPP: Be om eksplisitt godkjenning før du kjører kommandoer/tests som kan være destruktive, dyre, eller påvirke miljøet.
- STOPP: List the exact command(s)/tests you intend to run before asking for approval.
- Default: samle repro + plan først; kjør ingenting uten et tydelig “ja”.

## When to use
- A bug is reported with unclear root cause.
- Tests fail locally/CI or the failure is flaky.
- The system “doesn’t work” and you need a reliable repro.

## When NOT to use
- The task is primarily design/architecture (use `architecture-review`).
- The next step is simply to run final checks before finishing (use `verification-before-completion`).

## Escalation — dual-brain council
If the first hypothesis pass is falsified with no survivor, the failure is flaky, or it spans
domains, recommend escalating to the Claude-side `/debug` council mode (parallel independent
Claude + GPT research on the same repro, then 2–3 candidate fixes raced in disposable worktrees).
This skill remains the single-pass lane; the council is the deep lane.

## Inputs
- Repro steps (minimal), environment details, and expected vs actual behavior.
- Any logs/error messages, plus the failing command/test name if known.
- Constraints (time, scope, files you do NOT want touched).

## Outputs
- Format: Debugging Report.
- Example:
```
## Debugging Report
- Goal: ...
- Inputs: ...
- Findings: Repro + evidence + leading hypothesis
- Recommendations: Minimal fix plan
- Risk: ...
- Verification: <cmd> -> PASS/FAIL
```

## Allowed tools and prohibited actions
- Note: `allowed-tools` in frontmatter is informational only; follow these tool/safety rules as policy.
- Allowed tools: codebase readFile search usages changes problems todos edit runCommands runTests testFailure
- Prohibited actions: No secrets/PII. No deploys. No destructive commands. No dependency upgrades unless explicitly requested.

## Steps
1. **Stabilize the repro**
   - Write minimal repro steps + expected/actual.
   - If flaky, record frequency, seed/time window, and any environment differences.
2. **Trim the working set**
   - Identify the smallest set of files/components that can plausibly cause the issue.
   - If you suspect drift/poisoning, run `context-health-check`.
3. **Form hypotheses**
   - List 2–5 hypotheses, each with a quick test to falsify.
4. **Collect evidence**
   - Prefer deterministic checks (small tests, targeted logs) over broad changes.
   - Run the smallest relevant command/test first (with approval).
5. **Apply the minimal fix**
   - Change as little as possible; avoid refactors unless required to fix.
6. **Verify**
   - Re-run the failing repro/test and at least one adjacent check (if available).
7. **Document**
   - Record what was run and the outcome (`command -> PASS/FAIL`) and what remains.

## Verification
- Provide the exact command(s) run and outcome (`PASS/FAIL`), or explain why running wasn’t possible.

## Risks / failure modes
- Chasing symptoms instead of root cause (missing repro).
- Over-scoping and introducing unrelated changes.
- Flaky tests masking regressions; verify deterministically when possible.

## References
- `.codex/CONTINUITY.md`
- `~/.codex/skills/.system/skill-creator/SKILL.md`

## Next recommended skill(s)
- If the fix is non-trivial: `risk-assess`, then implement.
- Before reporting “done”: `verification-before-completion`.
- If tests are missing: `test-coverage`.
- If docs should change: `update-documentation`.

## Example prompts
- "Bug: login fails locally. Use systematic-debugging to get a repro, form hypotheses, and propose a minimal fix."
- "CI test failure is flaky; do systematic-debugging and tell me what to run and what evidence you need."
