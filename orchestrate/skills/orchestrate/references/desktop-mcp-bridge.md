# Running the loop from Claude Desktop (Codex as an MCP tool)

Claude Desktop can't run arbitrary Bash, so it can't call `codex exec` directly the way Claude Code (CLI) can. Bridge Codex in as an **MCP tool** using Codex's own server mode, then Claude in Desktop can hand execution to Codex for steps 2/3/6 and review the PR via the GitHub connector.

> Codex `mcp-server` is experimental. Verify the exposed tool surface with `codex mcp-server --help` before relying on it. If it changes, fall back to running the loop from Claude Code (CLI) — the more robust surface for unattended work anyway.

## Setup
1. Confirm serve mode: `codex mcp-server --help` (runs Codex as an MCP server over stdio).
2. Find your codex binary path: `command -v codex`.
3. Add it to Claude Desktop's MCP config (`claude_desktop_config.json`; on macOS it's under `~/Library/Application Support/Claude/`). Use the absolute path from step 2 so Desktop's launch env finds it:
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
4. Fully quit and reopen Claude Desktop. Confirm a `codex` tool appears.
5. Verify with a read-only call first (e.g. "use the codex tool to summarize this repo") before letting it write.

## How the loop maps onto Desktop
- **Plan / review PR (Claude side):** done natively in Desktop; review the PR diff via the GitHub connector or by pasting `gh pr diff <n>` output.
- **Critique / execute / fix (Codex side):** call the `codex` MCP tool with the same prompts the skill uses. Whether the MCP tool honors sandbox/approval flags depends on the server build — treat Desktop runs as **supervised by default** and confirm writes.
- **Deploy:** same risk gate as CLI; Desktop should human-gate deploy.

## Recommended split
- **Kick off + PR review in Desktop** (nice for reading diffs and quick approvals).
- **Unattended end-to-end loop in Claude Code (CLI)** — it has Bash, the full flag surface, `--dry-run`, and the `scripts/orchestrate.sh` driver. The `HANDOFF-*.md` batons let you start in one surface and resume in the other.

## Alternative (expose Codex to Claude Code)
`claude mcp add codex -- <path-to-codex> mcp-server`. Usually unnecessary — the CLI already calls `codex exec` via Bash.
