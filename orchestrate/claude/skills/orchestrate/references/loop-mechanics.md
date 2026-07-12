# Loop mechanics — Codex CLI flags, resume, runaway/cost rails

Verified against Codex CLI `0.142.5` (ChatGPT-OAuth login; config defaults `model = gpt-5.6-sol`, `model_reasoning_effort = xhigh`, 1M ctx).

## Codex exec flags used by the loop
- `-s, --sandbox read-only | workspace-write | danger-full-access` — critique uses `read-only`; execute/fix use `workspace-write`.
- **Approvals:** `codex exec` has **no `-a` flag** (that's on the top-level `codex` only). For headless runs pass **`-c approval_policy=never`** so Codex doesn't block waiting on an approval (the config default is `on-request`, which WILL block).
- **Network:** `read-only` and `workspace-write` both **block network**. So Codex commits locally; the driver/Claude (outside the sandbox) does `git push` + `gh pr create`. To let Codex itself reach the network, either add `-c sandbox_workspace_write.network_access=true` or use `--dangerously-bypass-approvals-and-sandbox`.
- `--dangerously-bypass-approvals-and-sandbox` — full autonomy, no sandbox, has network. **Only inside a throwaway git worktree.** There is no `--full-auto` in this version.
- `-o, --output-last-message <file>` — capture Codex's final message cleanly (what the loop reads).
- `--json` — JSONL event stream (thread.started, turn.*, item.*, error) for programmatic drivers.
- `--output-schema <file>` — constrain the final answer to a JSON schema (use for machine-parsed step results).
- `-C, --cd <dir>` / `--add-dir <dir>` — set the working root / extra writable dirs.
- `-c model_reasoning_effort=low|medium|high|xhigh|ultra` — per-call effort override.
- **Per-step defaults in this loop:** critique (step 2) and PR review keep the config's default model (Sol) at `xhigh`/`ultra` — no `-m` flag. The mechanical implement (step 3) and fix (step 6) steps default to **`gpt-5.6-terra` at `ultra`** (via `ORCH_EXEC_MODEL` / `ORCH_EXEC_EFFORT`, or `exec_effort` in `.ai/orchestrate.toml`); terra·ultra lands near Sol Extra-High quality at ~1/3 the Sol Ultra cost. An active override from the dashboard overrides panel takes precedence over these env defaults while it lasts.

## Resume / threading
- `codex exec resume <SESSION_ID> "<follow-up>"` — resume a specific session.
- `codex resume` / `codex fork` — interactive resume / branch a session.
- Separate `codex exec` calls do NOT share context unless resumed — thread the plan→critique→implement→fix chain via resume, or re-supply context via the handover file.

## Hands-off vs supervised
- **Hands-off (default):** steps 2–6 run without stopping. Fold non-blocking critique automatically; only blocking PR-review findings loop back to Codex; stop only at a risky deploy or the iteration cap.
- **Supervised (`--supervised`):** pause after each step (plan-approval, execute, PR-review, edits, deploy) and show the captured output before continuing.

## Runaway & cost rails
- **Iteration cap** on step 5↔6 (`max_iter`, default 3) — after the cap, stop and escalate with the outstanding findings rather than thrashing.
- **Checkpoint every step** to `.ai/` memctl (`orchestrate.<topic>` = step/branch/pr/iter). Codex runs on the ChatGPT plan's limits — a killed run must **resume**, not restart from zero.
- **Branch-per-task + PR always** — no direct `main` writes; blast radius stays in the PR.
- **`--dry-run`** prints the command plan without executing — use it to sanity-check the loop on a new repo before letting it run.
- If a `codex exec` errors or hits a limit, surface the error and stop; do not blind-retry.

## Unattended CLI driver
The driver `scripts/orchestrate.sh <topic>` automates **steps 2–4 only** (the Codex critique/implementation/PR leg), captures the exact implementation session ID, writes the review baton, and enters `handoff`. Run **steps 5–7 in a Claude session**: review the PR, resume that recorded session ID for fixes, and make the deploy decision. Poll PR/CI with `/loop` (e.g. `/loop 5m gh pr checks <n>`).
