# Auto-deploy safety (step 7)

Auto-deploy is irreversible and outward-facing, so it is gated hard. Default to NOT deploying when anything is uncertain.

## All of these must be true to auto-deploy
1. **Human-authorized target**: `.ai/orchestrate.toml` contains `deploy_authorized = true`, **set by the user** (a person), recording that they have opted this specific repo into unattended auto-deploy. The orchestrator must **never write this key or self-authorize a deploy target** — an agent choosing to deploy its own PR to prod is exactly what a deploy guardrail should block. Absent/false → human-gate. A general "auto-deploy is fine" preference or a one-off "yes, merge this PR" is **not** standing per-repo authorization; only this flag is.
2. **Risk = low** (see classifier below).
3. **CI green**: `gh pr checks <n>` shows all required checks passed.
4. **PR mergeable**: `gh pr view <n> --json mergeable,mergeStateStatus` is clean (no conflicts, not blocked).
5. **Deploy mechanism configured**: `.ai/orchestrate.toml` defines `deploy_cmd`, `deploy_skill`, or `deploy_via = "git-merge"` (git-integrated hosts like Vercel/Netlify where merging to main IS the deploy). **None → human-gate.** Never invent a deploy mechanism.

If any fails: **stop, summarize, hand deploy to the user.** Even with 2–5 green, never merge an agent's own PR to a production target unless the human set `deploy_authorized = true` in advance. Many hosts/permission modes will also block an agent self-merge to prod at the platform level — treat that as the guardrail working, not a bug.

## Risk classifier — hard "always-gate" exclusions
A change is **NOT low-risk** (→ human gate, never auto-deploy) if the diff touches ANY of:
- Auth, permissions, or session handling
- Secret handling (env vars, tokens, keys)
- Database migrations or destructive SQL
- File/branch deletion, force-push, or other irreversible ops
- Public API or contract changes
- Production or CI/CD config
- Infrastructure / IaC (Terraform, Bicep, ARM, Pulumi, k8s manifests)
- Net diff larger than ~300 lines

**Low-risk** = none of the above, small diff, additive/localized change, tests cover it, CI green. Examples: add a pure function + test, a copy tweak, a new isolated endpoint with tests, a dependency patch bump that passes CI.

## `.ai/orchestrate.toml` schema (per repo; gitignore it if you like)
```toml
# All keys optional; sane defaults applied when absent.
deploy_authorized = false           # REQUIRED true to allow unattended auto-deploy. Set by a HUMAN only,
                                    # never by an agent. Absent/false => deploy is always human-gated.
deploy_cmd   = "npm run deploy"     # command run on auto-deploy; absent => human-gate deploy
deploy_skill = "your-deploy-skill"  # OR name a deploy skill instead of a raw command
deploy_via   = "git-merge"          # OR for git-integrated hosts (Vercel/Netlify): merging main IS the deploy
ci_gate      = true                 # require gh pr checks green before deploy (default true)
max_iter     = 3                    # review<->fix loop cap (default 3)
sandbox      = "workspace-write"    # codex exec sandbox for the implement step (default workspace-write)
exec_effort  = "medium"             # gpt-5.5 reasoning effort for implement/fix (critique + review stay xhigh)
auto_merge   = false                # merge the PR before deploy (default false: leave merge to the user)
```

## Merge policy
- Authorized + low-risk + green + `auto_merge = true` → `gh pr merge <n> --squash --delete-branch`, then deploy (or, for git-integrated hosts, the merge *is* the deploy).
- Otherwise leave the PR open for the user to merge; report it's ready.
