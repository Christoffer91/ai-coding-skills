# Loop mechanics — Codex CLI flags, resume, runaway/cost rails

Verified against Codex CLI `0.14x` (ChatGPT-OAuth login; config default `model = "gpt-5.6-sol"`). Re-check with `codex exec --help` if your version differs.

## Codex exec flags used by the loop
- `-s, --sandbox read-only | workspace-write | danger-full-access` — critique uses `read-only`; execute/fix use `workspace-write`.
- **Approvals:** `codex exec` has **no `-a` flag** (that's on the top-level `codex` only). For headless runs pass **`-c approval_policy=never`** so Codex doesn't block on an approval prompt (the interactive default is `on-request`, which WILL block).
- **Stdin (deadlock trap):** `codex exec` reads stdin even with an arg prompt (to append a `<stdin>` block). A backgrounded/piped launch has an open pipe that never EOFs → codex hangs **forever** on *"Reading additional input from stdin…"* (a silent multi-hour zombie doing no work). **Always redirect stdin:** `codex exec [flags] - < prompt.md` (preferred; also dodges shell-quoting) or `codex exec [flags] "<prompt>" < /dev/null`. If stuck on that line for >1–2 min it's hung — kill precisely by cwd (`pgrep -f "<cwd>"; kill -9 <pid>`) so parallel runs survive, then redispatch via `- < prompt.md`. (`codex review` is unaffected.)
- **Network:** `read-only` and `workspace-write` both **block network**. So Codex commits locally; the driver/Claude (outside the sandbox) does `git push` + `gh pr create`. To let Codex itself reach the network, add `-c sandbox_workspace_write.network_access=true` or use `--dangerously-bypass-approvals-and-sandbox`.
- `--dangerously-bypass-approvals-and-sandbox` — full autonomy, no sandbox, has network. **Only inside a throwaway git worktree.** There is no `--full-auto` flag.
- `-o, --output-last-message <file>` — capture Codex's final message cleanly (what the loop reads).
- `--json` — JSONL event stream for programmatic drivers.
- `--output-schema <file>` — constrain the final answer to a JSON schema (machine-parsed step results).
- `-C, --cd <dir>` / `--add-dir <dir>` — set the working root / extra writable dirs.
- `-c model_reasoning_effort=low|medium|high|xhigh` — per-call effort override.
- **Per-step effort in this loop:** critique and PR review keep the config default (judgment work); the mechanical implement/fix steps run at **`medium`** by default (configurable via `exec_effort` in `.ai/orchestrate.toml` or `ORCH_EXEC_EFFORT`). Coding a well-spec'd plan doesn't need max reasoning — it's faster and lighter, still on `gpt-5.6-sol`.

## Resume / threading
- `codex exec resume --last "<follow-up>"` — resume the most recent headless thread (used in step 6 to apply review edits with full prior context).
- `codex exec resume <SESSION_ID> "<follow-up>"` — resume a specific session.
- Separate `codex exec` calls do NOT share context unless resumed — thread the chain via resume, or re-supply context via the handoff file.

## Runaway & cost rails
- **Iteration cap** on step 5↔6 (`max_iter`, default 3) — after the cap, stop and escalate rather than thrashing.
- **Checkpoint** loop state (step/branch/PR#/iter) so a killed or switched session resumes at the right step. Codex on a ChatGPT/Codex plan is subject to that plan's limits — resume, don't restart.
- **Branch-per-task + PR always** — no direct `main` writes; blast radius stays in the PR.
- **`--dry-run`** (`ORCH_DRYRUN=1`) prints the command plan without executing — sanity-check on a new repo first.
- If a `codex exec` errors or hits a limit, surface the error and stop; do not blind-retry.
