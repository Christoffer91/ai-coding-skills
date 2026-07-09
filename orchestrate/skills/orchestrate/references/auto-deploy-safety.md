# Auto-deploy safety (step 7)

The user opted into **auto-deploy for low-risk changes**. Auto-deploy is irreversible and outward-facing, so it is gated hard. Default to NOT deploying when anything is uncertain.

## All of these must be true to auto-deploy
1. **Human-authorized target**: `.ai/orchestrate.toml` contains `deploy_authorized = true`, **set by the user** (a person), recording that they have opted this specific repo into unattended auto-deploy. The orchestrator must **never write this key or self-authorize a deploy target** — an agent choosing to deploy its own PR to prod is exactly what the deploy guardrail blocks. Absent/false → human-gate. Note: a general "auto-deploy low-risk" preference or a one-off "yes, merge this PR" is **not** standing authorization for a repo; only this per-repo flag is.
2. **Risk = low** (see classifier below).
3. **CI green**: `gh pr checks <n>` shows all required checks passed.
4. **PR mergeable**: `gh pr view <n> --json mergeable,mergeStateStatus` is clean (no conflicts, not blocked).
5. **Deploy mechanism configured**: `.ai/orchestrate.toml` defines `deploy_cmd`, `deploy_skill`, or `deploy_via = "git-merge"` (git-integrated hosts like Vercel/Netlify where merging to main IS the deploy). **None → human-gate.** Never invent a deploy mechanism.

If any fails: **stop, summarize, hand deploy to the user.** Even with 2–5 green, never merge an agent's own PR to a production target unless the human set `deploy_authorized = true` in advance.

> Note: recon found no standalone deploy CLI on this machine (only Codex's `vercel` plugin and the `azf-deploy`/`deploy-functions` skills for Azure). So auto-deploy is effectively opt-in per repo — it fires only once you wire `deploy_cmd`. Until then every repo human-gates deploy, which is the safe default.

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

This is the same criticality list used by the `codex` and `risk-assess` skills — reuse `/risk-assess` for the scored verdict and treat CONDITIONS/REVIEW/ESCALATE/BLOCKED as "gate."

**Low-risk** = none of the above, small diff, additive/localized change, tests cover it, CI green. Examples: add a new pure function + test, copy tweak, new isolated endpoint with tests, dependency patch bump that passes CI.

## `.ai/orchestrate.toml` schema (per repo, gitignored under `.ai/`)
```toml
# All keys optional; sane defaults applied when absent.
deploy_authorized = false           # REQUIRED true to allow unattended auto-deploy. Set by a HUMAN only,
                                    # never by an agent. Absent/false => deploy is always human-gated.
deploy_cmd   = "npm run deploy"     # command run on auto-deploy; absent => human-gate deploy
deploy_skill = "azf-deploy"         # OR name a deploy skill instead of a raw command
deploy_via   = "git-merge"          # OR for git-integrated hosts (Vercel/Netlify): merging main IS the deploy
ci_gate      = true                 # require gh pr checks green before deploy (default true)
max_iter     = 3                    # review<->fix loop cap (default 3)
sandbox      = "workspace-write"    # codex exec sandbox for step 3 (default workspace-write)
exec_effort  = "medium"             # gpt-5.6-sol reasoning effort for implement/fix (critique + review stay xhigh)
auto_merge   = false                # merge the PR before deploy (default false: leave merge to user unless low-risk+green)
```

## Merge policy
- Low-risk + green + `auto_merge=true` → `gh pr merge <n> --squash --delete-branch`, then deploy.
- Otherwise leave the PR open for the user to merge; report it's ready.
