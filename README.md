# ai-coding-skills

A small collection of portable **Claude Code + OpenAI Codex CLI** skills. One top-level folder per skill; inside each, a `claude/` and a `codex/` subtree hold that tool's variant, and anything at the skill root (dashboards, drivers, tests, contracts) is shared runtime. No personal config, paths, or credentials — bring your own logins.

## Skills

| Skill | Claude side | Codex side | What it does |
|---|---|---|---|
| [orchestrate](orchestrate/) | `/orchestrate` | `$orchestrate` | Dual-brain plan → execute → review → ship loop: **Claude** plans & reviews the PR, **Codex CLI** critiques the plan, writes the code, opens the PR, and applies review edits. Includes a localhost dashboard with click-to-answer gates. Deploy is risk-gated. |
| [pipeline](pipeline/) | `/pipeline` | `$pipeline` | Standard delivery pipeline for non-trivial work: coverage matrix (security/risk/review/tests/docs), adaptive routing, verification gates, PR-ready output. Routes real implementation into `orchestrate`. |
| [debug](debug/) | `/debug` | `$systematic-debugging` | Evidence-driven debugging. Hard bugs escalate to a dual-brain **council**: Claude + Codex research independently, hypotheses get falsified, candidate fixes race in disposable worktrees. Token-conscious, with a usage report. |
| [critique](critique/) | `/critique` | (Codex ships its own) | Fair-but-rigorous critical-friend pass on an idea/plan/prompt/architecture before you commit — steelman, challenge, calibrated verdict. Modes: rubber-duck / critique / hard-challenge / decision. Optional parallel subagent lenses + independent second-model opinion. |

## Install a skill

Quickest — this repo is a Claude Code **plugin marketplace** (skill-only installs, no clone needed):

```
/plugin marketplace add Christoffer91/ai-coding-skills
/plugin install orchestrate@ai-coding-skills
/plugin install pipeline@ai-coding-skills
```

For orchestrate's full runtime (localhost dashboard, headless driver, Codex-side skill) clone and run the installer — it asks about each optional layer, all defaulting to No; each skill folder has its own `README.md`:

```bash
cd orchestrate && ./install.sh        # Claude skill + dashboard, and codex/ side if ~/.codex exists
```

For skills without an installer, copy the subtree you want:

```bash
cp -R pipeline/claude/skills/pipeline ~/.claude/skills/pipeline
cp -R pipeline/codex/skills/pipeline  ~/.codex/skills/pipeline
```

## Contributing / adding a skill (keep it clean)

Only **genericized** skills go here — no usernames, emails, absolute home paths, private repo names, org/cloud IDs, or personal memory-system wiring. Keep your personal, config-wired versions in a private dotfiles repo. New skills follow the same shape: `<skill>/claude/skills/<skill>/`, `<skill>/codex/skills/<skill>/`, shared runtime at the skill root.

Before committing, run the guard:
```bash
./scan-pii.sh                       # scans for home paths + emails
PII_EXTRA='yourname|your-handle|private-repo' ./scan-pii.sh   # add your own tokens
```

## License
MIT — see [LICENSE](LICENSE).
