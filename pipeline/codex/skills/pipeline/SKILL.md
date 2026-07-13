---
name: pipeline
description: "Use when non-trivial Codex work needs canonical triage, adaptive model routing, spec-driven planning, critique, risk gates, implementation, verification, docs, or PR readiness. It is the single entrypoint and routes small safe work to cheaper execution, full specs to `orchestrate`, and approved bounded plans to `loop-controller`. Triggers: $pipeline, pipeline, standard pipeline"
allowed-tools: "codebase readFile search usages changes problems fetch todos edit runCommands runTests testFailure"
---
# Pipeline

## SAFETY GATE
- Default: `PLAN_ONLY` means no file edits, deploys, installs, destructive commands, or state-changing actions.
- In `PLAN_ONLY`, read files and run safe read-only discovery commands when needed to produce an accurate plan.
- In `EXECUTE`, proceed with requested safe edits and non-mutating validators. State commands before running them when practical.
- STOPP: Ask before deploy/publish/apply, installs, destructive commands, credential changes, expensive/long-running jobs, or any command outside the user's apparent intent.
- STOPP: If a command allowlist was explicitly agreed, ask again before adding commands outside that allowlist.
- STOPP: Ask before running external/paid model review tools such as Claude Code CLI or `claude ultrareview`; print the exact command first.

## Purpose
One entrypoint skill to enforce the “Standard Pipeline” across chats: adaptive model routing, spec-driven plans when justified, fresh plan critique, continuity, safety gates, verification, documentation, and PR-ready output.

This pipeline is the canonical entrypoint for non-trivial Codex work. External workflow packs and research can inform the approach, but they do not replace this flow unless explicitly adopted.

## When to use
- At the start of any non-trivial task (code/config changes, behavior changes, user-visible work).
- When the user asks for a “full workflow” / “pipeline” / end-to-end handling.
- When work is long-running and needs checkpoints and continuity updates.

## When NOT to use
- Trivial Q&A that won’t lead to changes.
- When a single narrow skill is clearly sufficient and the user explicitly wants only that (e.g. “just write a PR description”).

## Inputs
- Goal + success criteria (1–3 bullets).
- Triage hints (pick one or more): `frontend`, `backend`, `infra`, `security`, `incident`, `perf`, `debugging`, `docs`, `dependencies`, `PR/CI`.
- TDD_MODE: `on`|`off` (default `off`).
- Constraints (time, risk tolerance, areas to avoid).
- Relevant paths/files and any known commands/tests.
- Continuity track (required for multi-hour or multi-project work): `.codex/continuity/<track>.md`
- Mode: `PLAN_ONLY` (default unless implementation is clearly requested) or `EXECUTE`.
- Execution profile: `EXECUTION_PROFILE=AUTO|DIRECT|FAST|STANDARD|DEEP` (default `AUTO`).
- Spec mode: `SPEC_MODE=AUTO|MICRO_SPEC|FULL_SPEC` (default `AUTO`).
- Plan critique: `PLAN_CRITIQUE=AUTO|INTERNAL|CLAUDE|OFF` (default `AUTO`).
- Orchestrate recursion guard: `CALLER=orchestrate` with `CONTRACT_ONLY=true` when the planner invokes this pipeline only to produce a contract.
- If `EXECUTE`: optional command allowlist or explicit stop gates.
- If execution should be bounded across iterations: route the approved plan to `loop-controller` with a continuity track, working set, and command allowlist.
- Optional Claude review gate: `CLAUDE_REVIEW=off|requested|required` remains a compatibility alias. `requested|required` selects `PLAN_CRITIQUE=CLAUDE`, but the external call still requires approval of the exact command.

## Outputs
- Format: `Pipeline Plan` (PLAN_ONLY) or `Pipeline Execution Report` (EXECUTE).
- Required output sections (even if brief):
  - BRIEF (normalized goal/non-goals/constraints/acceptance criteria)
  - TRIAGE (classification + execution profile + routing reason)
  - DESIGN/SPEC (acceptance criteria + constraints)
  - KARPATHY SANITY GATE (assumptions, simpler alternative, surgical scope, done criteria)
  - PLAN (step-by-step, with verification per step; TDD_MODE if enabled)
  - Coverage Matrix (final)
- Example:
```
## Pipeline Plan
- Goal: ...
- Mode: PLAN_ONLY
- Triage / execution profile / routing reason: ...
- Spec mode / plan critique: ...
- Working set (initial): ...
- Design/Spec: ...
- Karpathy Sanity Gate: ...
- Plan (with verification per step): ...
- Coverage Matrix: ...
- Risk + gates: ...
- Verification plan: <cmds to run later; not executed>
```

## Allowed tools and prohibited actions
- Note: `allowed-tools` in frontmatter is informational only; follow these tool/safety rules as policy.
- Allowed tools: codebase readFile search usages changes problems fetch todos edit runCommands runTests testFailure
- Prohibited actions: No secrets/PII. No silent command execution. No deploy/publish without explicit user approval and the relevant deploy/release skill. No importing untrusted content without license checks.

## Steps

### 0) Mode selection
1. Default to `PLAN_ONLY` for pure planning/review requests.
2. Treat explicit requests like "fix", "do it", "implement", "run the checks", or "do the rest" as `EXECUTE` unless a stop gate applies.
3. In `PLAN_ONLY`, gather enough repo-grounded evidence to make the plan accurate, but do not edit files.
4. In `EXECUTE`, keep edits scoped and run relevant non-mutating validators. Apply STOPP gates only for actions listed in SAFETY GATE.

### 0a) BRIEF NORMALIZATION (before triage)
1. Restate the request in 1-2 lines.
2. Capture four fields explicitly before detailed routing:
   - Goal
   - Non-goals
   - Constraints
   - Acceptance criteria
3. If the request is materially vague after one normalization pass, run `ask-questions-if-underspecified`.
4. Treat this brief as the canonical reference for the rest of the pipeline; do not let later steps drift from it.

### 0b) ADAPTIVE EXECUTION PROFILE
1. Resolve `EXECUTION_PROFILE=AUTO|DIRECT|FAST|STANDARD|DEEP`; default to `AUTO` and report the selected profile plus concrete reason.
2. `DIRECT`: no model-routed subagents. Use only for Q&A, critique-only work, or a tiny non-mutating response where delegation costs more than the task.
3. `FAST`: one bounded mechanical or local change with a known solution, reversible scope, no unresolved design choice, and one deterministic focused check. Produce a `MICRO_SPEC`, then route the approved edit to `orchestrate_executor` (Terra medium) without Sol Ultra planner or reviewer.
4. `STANDARD`: behavior or design changes with clear boundaries but meaningful acceptance, interface, test, or multi-file decisions. Route through `orchestrate` with a Sol Ultra `FULL_SPEC`, fresh internal plan critique, Terra execution, fresh final review, and optional/non-fatal shared status emission per `orchestrate/references/shared-run-status.md`.
5. `DEEP`: security/auth/privacy, destructive or irreversible work, migrations, dependencies with broad impact, public API/schema changes, architecture boundaries, production incidents, ambiguous failures, cross-repo work, or risk `REVIEW/ESCALATE/BLOCKED`. Use the full orchestrated route with deep evidence, human gates, and optional/non-fatal shared status emission per `orchestrate/references/shared-run-status.md`.
6. Risk and uncertainty override apparent size. A one-file auth change is `DEEP`; a deterministic mechanical multi-file rewrite may remain `FAST` when invariants and verification are explicit.
7. Escalation is one-way: `FAST -> STANDARD -> DEEP`. Do not reset or downgrade the profile by rephrasing the task. Replan when scope, risk, acceptance criteria, dependencies, or evidence materially change.
8. A skill cannot change the active parent model. Adaptive savings come from bounded delegation to model-pinned agents; the current task still performs the small routing decision.
9. When `CALLER=orchestrate` and `CONTRACT_ONLY=true`, produce the requested plan contract and return it to the conductor. Do not route recursively back to `orchestrate`, spawn an executor, or create a second state record.

### 0c) SPEC AND CRITIQUE POLICY
1. Resolve `SPEC_MODE=AUTO|MICRO_SPEC|FULL_SPEC`.
   - `FAST` -> `MICRO_SPEC`: goal, non-goals, working set, invariant, success signal, focused check, and stop gates.
   - `STANDARD` or `DEEP` -> `FULL_SPEC`: use `references/spec-driven-plan.md`, produced by `orchestrate_planner` on GPT-5.6 Sol Ultra.
   - `DIRECT` -> no implementation spec unless the user explicitly requests one.
2. Do not force `FULL_SPEC` onto trivial or purely mechanical work. Spec depth follows decision complexity, not ceremony.
3. Every `FULL_SPEC` must have a completed critique before implementation. A new or materially revised `FULL_SPEC` requires a fresh critique; an unchanged approved contract may reuse its recorded completed `Critique disposition` when resuming.
   - `PLAN_CRITIQUE=AUTO|INTERNAL` -> `orchestrate_plan_critic` follows `critique` without planner rationale.
   - `PLAN_CRITIQUE=CLAUDE` -> use the approval-gated Fable-to-Opus procedure in `orchestrate/references/claude-plan-critique.md`.
   - `PLAN_CRITIQUE=OFF` -> plan-only inspection. For `EXECUTE` with a `FULL_SPEC`, stop at `AWAIT_APPROVAL`; no executor may run until an internal or approved Claude critique completes. An explicit override cannot bypass this implementation gate.
4. Record accepted and rejected concerns under `Critique disposition`. Material changes to scope, invariants, acceptance criteria, commands, or risk return to approval.

### A) TRIAGE (classify the work early)
1. Classify the request into one or more tracks (use the most specific that fits):
   - Frontend: HTML/CSS/JS/UI, pages/components, UX polish.
   - Backend: Azure Functions, API behavior, Python/JS runtime changes, cache logic.
   - Infra/Deploy: release readiness, environment config, publishing/deploy steps.
   - Security: auth/CORS/secrets/input validation, security review requests.
   - Incident: prod/outage/availability issues, urgent mitigation + postmortem.
   - Performance: latency/slow UI/API/cache, cost hot-spots.
   - Debugging: test failures/flaky tests/unknown root cause.
   - Codebase Understanding: unfamiliar feature/system area, request-flow tracing, data-flow mapping, "explain how this works", "map before I edit".
   - Docs: README/docs/changelog updates.
   - Dependencies: npm/pip upgrades, lockfile churn, vuln remediation.
   - PR/CI: GitHub Actions failures, PR comments/reviews.
   - Skill/Runtime Hygiene: repeated-work mining, skill cleanup, runtime drift.
   - Local Ops: Codex memory, workstation diagnostics, local automations, daily bug scans.
   - Critique/Sanity: critical sparring, rubber-duck review, assumption challenge, devil's advocate before deciding.
   - Model Evaluation: model/prompt/reranker comparisons and judge output.
2. Decide `CHANGE_TYPE`:
   - `Q&A` (no changes) | `docs-only` | `code/config` | `release/deploy`
3. Resolve and record `EXECUTION_PROFILE`, `SPEC_MODE`, `PLAN_CRITIQUE`, routing evidence, and any override before selecting domain skills.
4. Decide routing (explicit skill order) and note it in the output:
   - If `CHANGE_TYPE=code/config` or `release/deploy`: run `risk-assess` before implementation; it includes the security touchpoint scan.
   - If the task is security-sensitive, run `security-review` before `risk-assess` or as part of the risk evidence.
   - If UI is in scope: run `frontend-design` before `ux-review`.
   - If the task is `STANDARD` or `DEEP`, route the plan contract through `orchestrate`; use `workflow-orchestrator` only when an additional multi-domain review map is materially useful.
   - If `CLAUDE_REVIEW=requested|required`, or risk is `REVIEW` or higher and the user approves a second opinion, run `claude-code-review` before implementation.
5. Recommended routing patterns (adapt as needed, keep the order):
   - Frontend: `frontend-design` -> `ux-review` -> `test-coverage` -> `verification-before-completion` -> `prepare-pr`
   - Backend: `architecture-review` (if design choices) -> `risk-assess` -> `test-coverage` -> `verification-before-completion` -> `prepare-pr`
   - Dependencies: `update-dependencies` -> `risk-assess` -> `verification-before-completion` -> `prepare-pr`
   - PR/CI failing: prefer GitHub plugin `gh-fix-ci`; use `gh-fix-ci` only as local CLI fallback -> `verification-before-completion` -> `prepare-pr`
   - PR comments: prefer GitHub plugin `gh-address-comments`; use `gh-address-comments` only as local CLI fallback -> `verification-before-completion` -> `prepare-pr`
   - Unfamiliar area before edit: `understand-large-codebases` -> (`architecture-review` if design choices) -> `risk-assess` -> `test-coverage` -> `verification-before-completion`
   - Debugging: `systematic-debugging` -> `verification-before-completion`
   - Performance: `performance-audit` -> (`architecture-review` if redesign) -> `risk-assess` -> `test-coverage`
   - Incident: `incident-response` -> (`security-review` if relevant) -> `risk-assess` (before any non-trivial code change)
   - Daily bug scan: `daily-bug-scan` -> (`systematic-debugging` + `test-coverage` only for concrete bugs) -> `verification-before-completion`
   - Critique/sanity pass: `critique` -> downstream review/research/risk skill only if the critique finds a concrete gap
6. If classification is unclear or requirements are vague, STOPP and run `ask-questions-if-underspecified`.

### B) PIPELINE INTAKE (continuity + context stability)
1. Use a continuity track for multi-session, multi-hour, or risky work. If the user names a track, use only that track.
   - If no track is specified, infer an existing obviously relevant track only when safe; otherwise mention the recommended track path in the plan and continue.
   - Optional: read `.codex/CONTINUITY.md` as a non-authoritative index to suggest existing track names (do not treat it as “active” in multi-chat work).
2. Ensure the chosen track exists:
   - `PLAN_ONLY`: do not create files; propose the exact path if no suitable track exists.
   - `EXECUTE`: create the track from `.codex/continuity/TRACK.template.md` only when tracking is useful for this task.
3. Optional: keep `.codex/CONTINUITY.md` as a short non-authoritative index. Do not update it during ordinary implementation unless the user asks.
4. Update the chosen track with short bullets only (facts only; no transcripts):
   - Goal (incl. success criteria)
   - Constraints/Assumptions
   - Key decisions (as they happen)
   - State / Now / Next
   - Working set (files/commands/tests)
5. For multi-domain or multi-session work, treat the chosen continuity track as the default durable plan artifact.
   - Optional: if the repo already uses design/plan docs, note one explicit doc path in the plan.
   - Do not introduce external planning trees or third-party state machines by default.
6. Never edit other track files. If you need to switch tracks, STOPP and ask the user to confirm the new track path.
7. If the chat context feels degraded (looping, conflicting constraints, lost details), run `context-health-check` and/or `context-compress` and then continue from the stabilized facts.
8. **DASHBOARD STATUS (emit at pipeline start, not only when routing to `orchestrate`).** Any
   non-trivial run — every `EXECUTE`, and any `PLAN_ONLY` above `FAST` — must surface on the local
   dashboard so it isn't invisible while it works. This is observational and fail-open: never let it
   block, approve, or change the run. Do it here at intake, not reactively.
   - **Resolve the emitter (absolute path, no symlink needed):** if `orchestrate-status` isn't on PATH,
     use `$HOME/.claude/skills/orchestrate/dashboard/orchestrate-status` when executable; else record
     `shared status: NOT_AVAILABLE` and skip silently. (No `~/.local/bin` symlink — that would trip the
     SAFETY GATE; the absolute path is enough for Codex.)
   - **Codex session sidecar (optional, strict session correlation):** when this host exposes both the
     exact absolute rollout JSONL path **and** the exact current Codex `turn_id`, pass both on the
     first `start` as `--codex-session "$ROLLOUT" --codex-turn "$TURN_ID"`, then optionally resolve
     and background `orchestrate-codex-sidecar --id "$RUN_ID" --session "$ROLLOUT" --turn "$TURN_ID"`.
     Never guess a newest rollout or launch it without the exact pair. The initial turn is immutable
     correlation metadata; recognized events in the bound rollout remain live across subsequent turns,
     including turnless `response_item` events.
     If either value is unavailable, record `codex sidecar: NOT_BOUND` and skip silently; Phase 1's
     `quiet` state remains honest. The sidecar is liveness-only: it writes an isolated lease, never
     calls `heartbeat`, never changes run JSON/steps/status, and never infers completion. The status
     record retains only opaque bindings, never the rollout path, raw turn id, transcript text, or tool
     output. See `orchestrate/references/shared-run-status.md` for lifecycle and launch details.
   - **Server:** if `$HOME/.claude/skills/orchestrate/dashboard/` exists and
     `curl -s -o /dev/null -w '%{http_code}' localhost:4600` isn't `200`, start it in the background
     from its real path: `nohup "$HOME/.claude/skills/orchestrate/dashboard/orchestrate-dashboard" >/tmp/orch-dashboard.log 2>&1 &`.
   - **Emit** per `orchestrate/references/shared-run-status.md`: a `start` with a FRESH unique id
     (`<repo>-<topic>-<branch>-<UTC>-<pid>` — never reuse a prior goal's id), then `step`/`pr`/`gate`
     at real transitions, and ALWAYS a terminal `done` (or `fail`) when the goal finishes or hands off.
     Wrap every call so a non-zero exit is non-fatal. Do this for the pipeline run itself even when the
     work never routes into `orchestrate` — that routing case only ADDS the orchestrate leg's emissions.

### C) DESIGN/SPEC (mandatory output)
1. For `FAST`, produce only the `MICRO_SPEC` fields from the adaptive contract. For `STANDARD` or `DEEP`, ask the Sol Ultra planner for the `FULL_SPEC` in `references/spec-driven-plan.md`, then complete the critique gate before approval.
2. The design/spec must cover at least:
   - Problem statement (1–2 lines)
   - Scope: IN / OUT
   - Constraints (time, "no new deps", compatibility)
   - Assumptions and ambiguity (ask only when ambiguity materially changes the plan)
   - Candidate approaches (1–2) + recommendation (only if there are real choices)
   - Simpler alternative considered (why it is enough or why it is rejected)
   - Surgical scope / working set boundary (files/areas to touch and do-not-touch areas)
   - Acceptance criteria (3–7 bullets, testable)
   - Risk notes (security/cost/perf) and mitigations (high level)
3. Domain add-ons (only when applicable):
   - Frontend: states (loading/empty/error), responsive behavior, keyboard flow/a11y.
   - Backend: API contracts, validation, error behavior, observability.
   - Dependencies: version targets, changelog scan plan, rollback.
   - PR/CI: what "green" means (which checks/tests must pass).

### D) PLAN (mandatory output, verification per step)
1. Produce implementation slices from the selected `MICRO_SPEC` or critiqued `FULL_SPEC`; every step has an explicit verification point:
   - Step -> expected outcome -> verification (command or manual check)
   - Every step should map to the user request or the explicit done criteria.
   - Do not include speculative flexibility or unrelated cleanup steps.
   - For `STANDARD` and `DEEP`, hand the critiqued and approved contract to `orchestrate`; it initializes or resumes `loop-controller` without replanning or duplicating state.
   - For `FAST`, hand one approved bounded objective to `orchestrate_executor`; enter `loop-controller` only after failure, scope expansion, pause/resume needs, or profile escalation.
2. For multi-domain or multi-session work, name the durable plan artifact explicitly.
   - Default: the chosen `.codex/continuity/<track>.md`
   - Optional: one repo doc path if the repo already keeps planning notes
3. If `TDD_MODE=on`, use RED–GREEN–REFACTOR explicitly:
   - RED: add a failing test (or a failing minimal repro)
   - GREEN: implement the smallest fix
   - REFACTOR: optional `code-simplifier` pass (working set only)
   - VERIFY: rerun the failing test + one adjacent check; finish with `verification-before-completion`

### E) COVERAGE MATRIX (decide what checks apply)
1. Produce a matrix for these domains and mark each as `REQUIRED` / `OPTIONAL` / `NOT_APPLICABLE` with a 1–2 bullet justification:
   - Security
   - Risk
   - Performance
   - Frontend Design (UI)
   - UX
   - Docs
   - Tests/Verification
   - Dependencies
   - PR/CI
   - Release/Deploy
   - Incident Response
2. Choose `REQUIRED` by default for Security + Risk on any `code/config`, `dependencies`, or `release/deploy` change, and for Tests/Verification on any behavior change.
3. If the working set touches UI (HTML/CSS/JS/pages/components), mark `Frontend Design (UI)` as `REQUIRED` and run it before `ux-review` (PLAN_ONLY: produce the design spec first).

### F) ORCHESTRATION (run the right existing skills in the right order)
For each domain that is `REQUIRED` or `OPTIONAL`, open and follow the corresponding skill’s `SKILL.md` and only load what you need.

Quick reference (when to use which skill):

| Skill | Use when | Typical order |
|---|---|---|
| `workflows` | User first needs a named route such as commit-push, deep-research-to-plan, frontend-ui, or skill-maintenance | Before this pipeline; selector only |
| `orchestrate` | `STANDARD` or `DEEP` delivery needs Sol Ultra full spec, bounded model routing, Terra execution, and fresh review | After pipeline triage; consumes this pipeline's contract |
| `critique` | A full spec needs independent challenge, or the user wants critical sparring before deciding | Required before approval for every `FULL_SPEC`; read-only |
| `workflow-orchestrator` | Broad/high-risk multi-domain work; internal review router, not a second pipeline | Early (PLAN_ONLY), before implementation |
| `loop-controller` | Approved bounded execution loop with state, budgets, command allowlist, verification, pause/resume, and stop gates | After plan/risk approval, before implementation iterations |
| `claude-code-review` | Explicitly approved Claude Code second opinion using Fable with Opus fallback | Optional replacement for the internal full-spec critique gate |
| `karpathy-guidelines` | Non-trivial work needs assumptions, simplest viable approach, surgical diff boundary, and done criteria | Inside DESIGN/SPEC/PLAN and before final verification |
| `understand-large-codebases` | You are new to an area, need request/data-flow tracing, or must explain/map a feature before editing | Early, before implementation and before broader review gates |
| `architecture-review` | You must decide boundaries/data flows/ops impact before coding | Before `risk-assess` and implementation |
| `security-review` | Security-sensitive or broad security work that may need audit/red/blue/risk lanes | Before `risk-assess` |
| `security-audit` | Narrow secrets/auth/CORS/validation scan | Before implementation when relevant |
| `risk-assess` | Any non-trivial change; required before implementation/deploy | Before implementation |
| `frontend-design` | Any UI/HTML/CSS/JS work needs a design spec + plan | Before `ux-review` |
| `ux-review` | UI/user flows changed; need WCAG/a11y + interaction review | After `frontend-design`, before finishing |
| `performance-audit` | Something is slow; you need metrics + bottleneck analysis | Before perf-focused refactors |
| `systematic-debugging` | Failing tests/bugs/flaky behavior need repro + hypotheses | Before broad refactors |
| `gh-fix-ci` | GitHub plugin skill for PR Actions failures; preferred when plugin is available | Before local debugging loops |
| `gh-fix-ci` | Local CLI fallback for PR Actions failures | Only when explicitly requested or plugin unavailable |
| `gh-address-comments` | GitHub plugin skill for PR review comments; preferred when plugin is available | After fixes, before final PR update |
| `gh-address-comments` | Local CLI fallback for PR review comments | Only when explicitly requested or plugin unavailable |
| `skill-hygiene-audit` | Repeated-work mining, skill cleanup, manifest/runtime drift, subagent opportunities | Early, before creating/updating skills |
| `skill-intake-review` | External/user-authored skill adoption review for usefulness, security, provenance, overlap, and performance cost | Before installing or adapting any new skill |
| `codex-memory-maintenance` | Local Codex/repo memory lookup, reconcile, drift, or durable fact updates | Early, before relying on memory-derived facts |
| `macos-release-readiness` | macOS release, installed app, LaunchServices, privacy/local gates | Before release or installed-app repair |
| `child-webapp-ipad-qa` | Child-facing web app iPad/local QA and WKWebView wrapper parity | Before public deploy or visual release sign-off |
| `imagegen-swarm` | Broad image concept exploration with numbered worker outputs and curation | Before visual asset selection |
| `ppt-imagegen-storyboard` | Experimental deck narrative review plus imagegen storyboard variants for PowerPoint/slide decks | Only when explicitly requested or when a deck creative pass clearly needs imagegen |
| `model-eval-judge` | Model/prompt/reranker comparisons requiring side-by-side evidence | Before changing runtime model config |
| `codex-health-check` | Codex app/runtime/session/memory/automation health is the question | Before cleanup or runtime mutation |
| `git-worktree-hygiene` | Repo/worktree/branch cleanup needs a read-only risk-ranked audit | Before destructive git cleanup |
| `daily-bug-scan` | Recent bug/regression scan should stay bounded and evidence-only | Before debugging or fixing |
| `automation-hygiene` | Recurring local automations need stale/noisy/unsafe review | Before automation mutation |
| `skill-usage-analytics` | Skill archive or optimization decisions need usage evidence | Before merge/archive decisions |
| `macos-workstation-diagnostics` | Battery, performance, process, disk, browser, or Codex slowdown diagnostics | Before cleanup or process mutation |
| `cowork-package-review` | Cowork package validation/rebuild, metadata, ZIP, dashboard rendering | Before package publish/upload |
| `test-coverage` | You need a concrete test plan / what to verify | Before `verification-before-completion` |
| `autoreview` | You want a local diff/branch review loop that validates findings and fixes in-scope issues before final checks | After implementation, before `verification-before-completion` |
| `verification-before-completion` | Before you say "done" / before merge | Near the end |
| `update-dependencies` | You need a safe dependency bump plan (no execution by default) | Early, before verification |
| `update-documentation` | README/docs/changelog must match behavior/config | After implementation, before PR |
| `prepare-pr` | You need a PR description with risk + verification evidence | After verification |
| `release-checklist` | Pre-deploy readiness check (no deploy) | Before `deploy-functions` |
| `deploy-functions` | You need deploy commands (do not run by default) | Last, after checks |
| `incident-response` | Prod/availability/security incident triage + postmortem | First for incidents |

Routing guidance (common cases):
- If `risk-assess` is REQUIRED, run it before any implementation.
- If this pipeline selects `STANDARD` or `DEEP`, return the critiqued spec, approved working set, command allowlist, success criteria, risk status, and stop gates to the `orchestrate` conductor; do not create a second state record.
- If `CALLER=orchestrate` and `CONTRACT_ONLY=true`, return the contract directly and stop; recursion is a routing defect.
- If implementation is in an unfamiliar area, run `understand-large-codebases` before implementation and before broader design/risk review.
- If the request is broad/high-risk, optionally run `workflow-orchestrator` early as a compact review gate.
- If you are stuck, switch to `systematic-debugging` and come back to the pipeline when the root cause is clear.
- If external workflow material is mentioned (for example Superpowers or GSD), treat it as reference input unless the user explicitly asks to adopt it.

### G) MODES (PLAN_ONLY vs EXECUTE)
1. `PLAN_ONLY` (default):
   - Output TRIAGE + DESIGN/SPEC + PLAN + Coverage Matrix and explicit checkpoints.
   - Safe read-only discovery is allowed; stop before file edits or state-changing actions.
2. `EXECUTE`:
   - Resolve `EXECUTION_PROFILE` before implementation and use the selected direct, FAST, STANDARD, or DEEP route.
   - Ask before any SAFETY GATE action or before expanding beyond an explicit command allowlist.
   - Record command outcomes as `command -> PASS/FAIL` when a continuity track is used.

### H) LONG-RUNNING CADENCE (milestones + stop conditions)
1. After each milestone (plan agreed, reviews done, implementation done, verification done), update the chosen continuity track with:
   - What changed
   - What was verified (`command -> PASS/FAIL`)
   - What’s next
2. Stop conditions:
   - If the same check fails 3 times without new evidence, STOPP and switch to `systematic-debugging` or ask the user for direction.
   - If scope expands beyond the TRIAGE + Coverage Matrix, STOPP and re-run them + risk gate.
   - If a `FAST` assumption fails, stop the executor and escalate to `STANDARD`; do not keep patching under the cheaper profile.

### I) FINAL EVIDENCE OUTPUT (PR-ready)
Produce a final report that includes:
- Files changed (paths)
- TRIAGE + DESIGN/SPEC (final)
- Coverage Matrix (final)
- Commands/tests run with outcomes (`command -> PASS/FAIL`)
- Risk summary + remaining risks (if any)
- Docs/PR readiness:
  - Any docs updated
  - PR description draft (or a link to `prepare-pr` output)
- Handoff note: 3–5 bullets with “what’s done / what’s next” and the next command to run (if applicable)
- Verification note:
  - Before saying "done", either run `verification-before-completion` or state exactly what was not verified and why.

## Verification
- The chosen `.codex/continuity/<track>.md` is updated with Goal/Constraints/Decisions/State/Working set.
- The output includes a BRIEF section before TRIAGE.
- TRIAGE + DESIGN/SPEC + KARPATHY SANITY GATE + PLAN sections exist in the output.
- TRIAGE records `EXECUTION_PROFILE`, `SPEC_MODE`, `PLAN_CRITIQUE`, and the evidence for each choice.
- Every `FULL_SPEC` was produced by the Sol Ultra planner and has a completed `Critique disposition` before implementation.
- Assumptions, simpler alternative considered, surgical scope / working set boundary, done criteria, and verification are explicit.
- A Coverage Matrix is produced and each REQUIRED domain has a referenced skill run (or a justified skip).
- If `EXECUTE` was used, the final output lists exact commands and outcomes.

## Risks / failure modes
- Over-scoping trivial work (mitigate by marking `NOT_APPLICABLE` early).
- Missing a relevant domain (mitigate with TRIAGE + Coverage Matrix + explicit justification).
- Unsafe command execution (mitigate with one-time allowlist approval + STOPP on new commands).
- Context drift over long runs (mitigate with continuity updates and `context-compress`).

## References
- `references/spec-driven-plan.md`
- `.codex/CONTINUITY.template.md`
- `.codex/continuity/README.md`
- `.codex/continuity/TRACK.template.md`
- `~/dev/repos/dotfiles/skills/codex/skills/`
- `~/.codex/skills/`

## Next recommended skill(s)
- For named workflow selection before planning: `workflows`.
- For model-routed end-to-end delivery: `orchestrate`.
- For broad/high-risk work: `workflow-orchestrator` (then implement skill(s) for the area).
- Before finishing: `verification-before-completion`, then `prepare-pr`.
- If context degrades: `context-health-check`, then `context-compress`.

## Example prompts
- "$pipeline PLAN_ONLY EXECUTION_PROFILE=AUTO: Produce the right-sized spec, routing evidence, critique gate, and verification plan."
- "$pipeline EXECUTE EXECUTION_PROFILE=AUTO: Route this through the cheapest safe profile and complete local verification."
- "$pipeline EXECUTE EXECUTION_PROFILE=DEEP PLAN_CRITIQUE=CLAUDE: Produce a Sol Ultra full spec, then request approval for the Fable-to-Opus critique gate."
