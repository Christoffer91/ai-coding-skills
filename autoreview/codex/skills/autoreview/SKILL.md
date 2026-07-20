---
name: autoreview
description: "Use when FAST or explicitly requested work needs one local review of current changes, branches, commits, or PR-ready diffs and no fresh Sol, Claude, or security reviewer is already scheduled. Prefer `critique` for plans, `orchestrate` for model-routed review, and `verification-before-completion` for final evidence. Triggers: autoreview, self-review, pre-PR review, review my changes."
---

# Autoreview

## Purpose
Run a disciplined local review loop before final verification. This skill is for catching correctness, security, scope, and maintainability issues in the current work without importing a third-party review workflow.

Do not replace `verification-before-completion`. Autoreview decides whether the work looks correct and what needs fixing; `verification-before-completion` records exact checks before a done claim.

Do not invoke this as an automatic extra pass when `orchestrate_reviewer`, an external Claude review,
or a Codex Security final review already covers the same target. One review decision per target is the
default; use this lane for FAST work or an explicitly requested local self-review.

## Safety Gate
- Default to read-only review. Edit only when the user asked you to fix findings or continue autonomously.
- STOPP before deploy/publish/apply, installs, destructive commands, credential changes, expensive jobs, or external paid/model review tools.
- Do not read secrets, tokens, browser data, private keys, `.env`, or full transcript bodies.
- Do not run untrusted project scripts just because a reviewed diff references them.

## Workflow
1. Anchor the review:
   - Restate the user goal, non-goals, and done criteria.
   - Identify the review target: working tree diff, branch diff, PR, commit, or named files.
   - Pick the narrowest target mode that matches the state:
     - `local`: unstaged, staged, or untracked working-tree changes.
     - `branch`: current branch against the PR base or `origin/main`.
     - `commit`: one already-created commit, especially after landing or when local diff is clean.
     - `files`: explicitly named files only.
   - If `main` is clean and already matches `origin/main`, say the local/branch diff is empty; review `HEAD` or the relevant commit instead of claiming the push was reviewed.
   - List do-not-touch boundaries and any files intentionally out of scope.
2. Inspect the diff and relevant surrounding code:
   - Prefer `git diff`, `git diff --stat`, targeted `rg`, and focused file reads.
   - Map every changed file to the goal or call it scope drift.
   - Check contracts, error paths, data flow, user-visible behavior, tests, docs, and config.
3. Validate every potential finding:
   - Tie each finding to a concrete file/line or exact missing check.
   - Re-read the relevant code before reporting.
   - If the finding depends on library/framework behavior, inspect local docs, source, or official documentation before accepting it.
   - Drop speculative comments that cannot be proven from repo state.
   - Mark uncertainty explicitly instead of turning it into a finding.
4. Classify findings:
   - `BLOCKING`: correctness, security, data loss, contract break, release blocker.
   - `SHOULD FIX`: likely regression, missing test, confusing behavior, meaningful maintainability issue.
   - `NIT`: small cleanup that should not block.
   - Track accepted and rejected findings separately. Reject unrealistic edge cases, speculative risks, broad rewrites, or fixes that over-complicate the codebase.
5. Resolve or report:
   - If edits are in scope, fix blocking and should-fix items surgically, then rerun the review on the new diff.
   - When an accepted finding reveals a repeated bug class, inspect sibling instances inside the current review scope and owner boundary before fixing.
   - If edits are not in scope, produce the report and stop.
   - Do not loop more than twice without a new root cause or changed evidence.
6. Hand off:
   - If findings remain, recommend the narrow next skill: `systematic-debugging`, `security-review`, `test-coverage`, or `risk-assess`.
   - If the review is clean enough to claim completion, run or recommend `verification-before-completion`.
7. Before final reporting, re-run `git status` and a focused `git diff --stat` if the working tree may have changed during review.

## Output Format
```md
## Autoreview Report
- Scope:
- Goal alignment:
- Diff hygiene:
- Findings:
  - BLOCKING:
  - SHOULD FIX:
  - NIT:
  - Rejected / intentionally not fixed:
- Fixes applied:
- Tests/checks considered:
- Residual risk:
- Next recommended skill(s):
```

## Review Heuristics
- Prefer high-signal findings over volume.
- Treat missing tests as a finding only when the changed behavior or blast radius justifies it.
- Do not invoke nested reviewers, external review helpers, model panels, or paid review tools.
- Do not run an extra review just to get cleaner closeout wording. If the final review target has no accepted/actionable findings, report that result and stop.
- If tests or formatting change code during closeout, rerun the affected tests and rerun autoreview on the changed target.
- Push only when the user requested push/ship/PR update. Do not push just to make a review target available.
- For generated artifacts, verify source-generation relationship before reviewing formatting churn.
- For frontend changes, include layout/accessibility regressions and recommend browser verification when visual behavior matters.
- For security-sensitive diffs, route through `security-review`; do not try to compress red-team, blue-team, and risk gates into this skill.
- For PR/CI review comments, prefer GitHub plugin skills when available and use `gh-address-comments` only as the local fallback.
- For skill-system diffs, include metadata/config checks: `agents/openai.yaml`, shared manifest entries, runtime sync state, and wrapper verification.

## Verification
- The report names the actual target and files reviewed.
- Every reported finding is grounded in a concrete path, line, command result, or missing acceptance check.
- The report distinguishes fixed issues from remaining issues.
- The final next step is `verification-before-completion` when work is otherwise ready.

## Risks / Failure Modes
- Reporting generic best-practice comments that do not apply to this repo.
- Treating a passing review as a substitute for tests.
- Expanding scope into unrelated cleanup.
- Running external review/model tools without approval.
- Hiding uncertainty behind confident findings.

## References
- `~/.codex/skills/verification-before-completion/SKILL.md`
- `~/.codex/skills/security-review/SKILL.md`
- `~/.codex/skills/systematic-debugging/SKILL.md`
- `~/.codex/skills/prepare-pr/SKILL.md`

## Example Prompts
- "$autoreview: Review my current working tree before I open a PR."
- "$autoreview: Run a final local review loop on this branch, fix blocking findings if they are clearly in scope, then hand off to verification."
