# Running the loop from Claude in Desktop (Codex as an MCP tool)

Claude in Desktop can't run arbitrary Bash, so it can't call `codex exec` directly the way Claude Code (CLI) can. Bridge Codex in as an **MCP tool** using Codex's server mode, then Claude in Desktop can hand execution to gpt-5.6-sol for steps 2/3/6 and review the PR via the GitHub connector.

> This guidance targets Codex `0.143+`. `mcp-server` remains an evolving surface, so verify it with `codex mcp-server --help`. Fall back to Claude Code (CLI) for unattended work if the exposed tools differ.

## Setup (macOS)
1. Confirm the serve mode exists: `codex mcp-server --help` (Codex runs as an MCP server over stdio).
2. Edit Claude Desktop's config: `~/Library/Application Support/Claude/claude_desktop_config.json`. Add (use the absolute codex path so Desktop's launch env finds it):
```json
{
  "mcpServers": {
    "codex": {
      "command": "/absolute/path/to/codex",
      "args": ["mcp-server"]
    }
  }
}
```
3. Fully quit and reopen Claude Desktop. Confirm a `codex` tool appears in the tools list.
4. In a Desktop chat, verify with a read-only call first (e.g. "use the codex tool to summarize this repo") before letting it write.

## How the loop maps onto Desktop
- **Plan / review PR (Claude side):** Opus does these natively in Desktop; review the PR diff via the GitHub connector (or paste `gh pr diff <n>` output).
- **Critique / execute / apply-edits (Codex side):** call the `codex` MCP tool with the same prompts the `/orchestrate` skill uses. Note: whether the MCP tool honors sandbox/approval flags depends on the server build — treat Desktop runs as **supervised by default** and confirm writes.
- **Deploy:** same risk gate as CLI; Desktop should human-gate deploy.

## Recommended split
- **Kick off + PR review in Desktop** (nice for reading diffs and quick approvals). Pair **Remote Control** in the Claude app when the phone is the interaction path; use `PushNotification` plus `AskUserQuestion` for each in-session gate.
- **Unattended end-to-end loop in Claude Code (CLI)** — it has Bash, the full flag surface, `--dry-run`, and the `scripts/orchestrate.sh` driver. The `HANDOFF-*.md` baton plus `~/.orchestrate/runs/<id>.json` let you start in Desktop and resume the same task in the CLI (or vice versa).

## Alternative (CLI-managed MCP)
To expose codex to Claude **Code** instead: `claude mcp add codex -- /absolute/path/to/codex mcp-server`. Usually unnecessary — the CLI already calls `codex exec` via Bash through the `codex` skill.
