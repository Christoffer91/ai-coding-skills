---
name: critique
description: "Use when an idea, plan, prompt, strategy, architecture/product choice, or proposed change needs fair but rigorous pushback before deciding. Fair-but-tough critical-friend pass; can fan out parallel subagent lenses and pull an independent Codex second opinion for high-stakes calls. Use instead of code-review for non-diff critique, architecture-review for system-boundary analysis, risk-assess for go/no-go scoring, and security-audit for security-sensitive decisions. Triggers: critique, rubber duck, challenge this, devil's advocate, kritisk blikk, utfordre dette, sanity check, pre-mortem."
allowed-tools: Read, Glob, Grep, WebSearch, WebFetch, Agent, Bash
---

# Critique

## Purpose
Give a fair, rigorous second-thought pass before the user commits to an idea, plan, product choice, prompt, architecture direction, or implementation approach.

This is a critical-friend skill, not a negativity skill. Challenge weak assumptions and missing evidence, but say plainly when the proposal is already solid.

## Modes
- `rubber-duck`: Help the user think. Ask a few sharp questions, reflect the shape of the problem, and avoid a verdict until the idea is clear enough.
- `critique`: Default. Steelman the idea, challenge it, and give a calibrated verdict.
- `hard-challenge`: Push harder with a pre-mortem, failure modes, incentives, edge cases, and what would make the plan obviously wrong.
- `decision`: Compare options against criteria, name the tradeoffs, and recommend the next move.

If the user does not name a mode, choose the lightest mode that fits. Do not make a simple question into a ceremony.

## Depth — solo, council, or dual-brain
Match effort to stakes; most critiques are solo and in-session.
- **Solo (default):** reason it through yourself. Right for almost everything.
- **Council (parallel subagents):** for a wide or high-stakes decision, fan out read-only `Explore`/`general-purpose` subagents, each attacking ONE distinct angle (e.g. evidence, alternatives, failure modes, cost) with no shared conclusions, then synthesize into ONE verdict — never ship parallel verdicts. Use when the surface is broad enough that one pass would miss a lens; skip when a single reading suffices.
- **Dual-brain second lens:** for a genuinely consequential call, pull an independent Codex opinion so the critique isn't single-model. Read-only, stdin-redirected, non-fatal:
  `codex exec -s read-only -c approval_policy=never -c model_reasoning_effort=high - < /tmp/critique-prompt.md > /tmp/critique-out.md`
  Fold its findings into your own verdict; you own the synthesis, Codex is one voice. Never let a failed/slow Codex call block the critique.

## Boundaries
- Default to read-only reasoning. Do not edit files, commit, push, install, deploy, publish, or mutate state from this skill. `Bash`/`Agent` are for read-only investigation and the optional Codex second lens only — never for changes.
- Do not replace `code-review` for diff review, `risk-assess` for formal go/no-go scoring, `architecture-review` for system design review, or `security-audit` for security-sensitive work.
- Do not invent blockers. If the idea is good, say so and name the remaining caveats.
- Do not ask a long list of questions. If a missing fact materially changes the verdict, ask up to three targeted questions or state conservative assumptions.
- Critique the idea, not the person. Be direct, specific, and useful.
- Do not use this skill to stall obvious implementation. If the critique is clean, say so and move to the next concrete step.

## Evidence Discipline
- Mark important claims as `Evidence`, `Inference`, or `Question` when the distinction matters.
- If you cannot verify a claim in the current context, say what assumption you are making. Prefer checking the repo/web over guessing.
- Avoid treating taste, fear, novelty, or effort as evidence.
- Prefer a small decisive test over broad speculation.
- For empirical objections, name the observation that would confirm or disconfirm the concern.
- For tradeoff objections, name what is traded against what. The sides must be in real opposition, not a preference disguised as a principle. If you cannot name both sides, it is taste, so cut it.

## Workflow
1. Choose the mode and depth (above).
2. Anchor the subject:
   - Restate the proposal in one or two sentences.
   - Name the decision being made.
   - Separate the user's stated facts from your assumptions.
3. Steelman before attacking:
   - State the strongest version of the idea.
   - Identify why a reasonable person would choose it.
4. Challenge:
   - Test hidden assumptions.
   - Look for unclear goals, missing constraints, weak evidence, overengineering, false urgency, scope creep, and irreversible choices.
   - Compare against the simplest sufficient alternative.
   - For code/config/security/release decisions, note when a formal downstream skill is required.
5. Calibrate:
   - Distinguish `must fix`, `should consider`, and `acceptable tradeoff`.
   - Mark uncertainty instead of turning guesses into findings.
   - If the plan is strong, say `Verdict: solid` and do not pad the report with weak objections.
6. Decide the next move:
   - Recommend proceed, revise, research, prototype, or stop.
   - Hand off only to the narrow next skill that is genuinely needed.

## Challenge Angles
- Goal clarity: Is the real objective explicit and testable?
- User value: Who benefits, and is the benefit concrete enough?
- Evidence: What facts support this, and what evidence is missing?
- Assumptions: Which assumptions would break the plan if false?
- Alternatives: Is there a simpler, cheaper, safer, or more reversible path?
- Risk: What can fail technically, operationally, financially, legally, or reputationally?
- Scope: Is this too broad, too narrow, premature, or mixing unrelated goals?
- Timing: Is this urgent, or just emotionally salient?
- Maintenance: Will future you or future agents understand and sustain it?
- Verification: What would prove the idea worked?

## Output Format
Default to `Short Critique` unless the idea is complex, high-stakes, or the user asks for a full report.

Hard caps: `Short Critique` <= 150 words. `Full Critique Report` <= 400 words. If you cannot fit under the cap, you have not prioritized hard enough: cut the weakest objections, do not compress the strong ones.

### Short Critique
```md
## Short Critique
- Verdict: solid | solid-with-caveats | needs-rework | stop-and-rethink
- Strongest version:
- Main challenge:
- Hidden assumption:
- Simpler / safer move:
- Next step:
```

### Full Critique Report
```md
## Critique Report
- Mode:
- Subject:
- Decision:
- My understanding:
- Strongest version:
- Main challenges:
- Hidden assumptions:
- Failure modes:
- Missing evidence:
- Simpler / safer alternative:
- Verdict: solid | solid-with-caveats | needs-rework | stop-and-rethink
- What would change my mind:
- Next recommended skill(s):
```

### Rubber-Duck Output
```md
## Rubber Duck
- What I think you are deciding:
- The key tension:
- Three questions:
- My current read:
- Next move:
```

### Decision Output
```md
## Decision Critique
- Options:
- Criteria:
- Tradeoffs:
- Recommendation:
- Risk to watch:
- Next step:
```

## Verdict Rules
- `solid`: the idea is coherent, useful, scoped, and evidence is sufficient for the decision.
- `solid-with-caveats`: proceed, but keep named caveats or verification steps visible.
- `needs-rework`: the direction may be right, but assumptions, scope, evidence, or design need revision before execution.
- `stop-and-rethink`: current plan is likely wrong, unsafe, too costly, or solving the wrong problem.

## Pushback Rule
- If the user responds with a new fact, genuinely re-evaluate. If the user is right, say so plainly and update the verdict.
- If the user responds with pressure only, such as "are you sure?" or "a source says you are wrong," do not capitulate. Re-reason from first principles and hold the verdict when the reasoning still holds.
- Treat citation-pressure as a known failure point: flipping on new information is strength; flipping on pressure alone is sycophancy.

## Anti-Patterns
- Contrarian theater: finding objections just to sound rigorous.
- Nitpicking: focusing on wording or tiny edge cases while ignoring the real decision.
- Generic caution: saying "be careful" without a concrete failure mode or test.
- Premature handoff: routing to another skill before giving the useful critique.
- Over-questioning: asking for more context when conservative assumptions are enough.
- Verdict inflation: using `stop-and-rethink` for ordinary caveats.
- Hidden implementation: making changes or running mutating tools under the cover of critique.
- Council theater: fanning out subagents for a decision one careful reading would settle.

## Handoff Rules
- Use `deep-research` when the main gap is external evidence or vendor/current-state uncertainty.
- Use `architecture-review` when the main gap is boundaries, data flow, dependencies, or operational design.
- Use `risk-assess` when the decision gates implementation, deployment, cost, security, or reversibility.
- Use `security-audit` (or `red-team` for attacker's-view) for auth, CORS, secrets, permissions, data exposure, prompt injection, or threat-model concerns.
- Use `frontend-design` or `ux-review` when the critique is about a user-visible surface.
- Use `code-review` only after there is a concrete diff or branch to review.
- Use `orchestrate` when a clean critique turns into non-trivial implementation to ship.

## Example Prompts
- "/critique: Challenge this product idea before I spend time building it."
- "/critique rubber duck: I think this architecture is right. Push back hard, but tell me if it is solid."
- "/critique hard-challenge: Pre-mortem this plan. What would make it fail?"
- "/critique decision: Should we build, buy, or defer this?"
- "/critique council: high-stakes call — fan out lenses and pull a Codex second opinion."
- "/critique: Kritisk blikk på denne planen. Hva overser jeg?"
