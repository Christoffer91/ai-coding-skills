# ai-coding-skills

A small collection of portable **Claude Code + OpenAI Codex CLI** skills. One top-level folder per skill; inside each, a `claude/` and a `codex/` subtree hold that tool's variant, and anything at the skill root (dashboards, drivers, tests, contracts) is shared runtime. No personal config, paths, or credentials — bring your own logins.

## Skills

| Skill | Claude side | Codex side | What it does |
|---|---|---|---|
| [orchestrate](orchestrate/) | `/orchestrate` | `$orchestrate` | Bounded plan → execute → review loop: Codex Sol handles planning and judgment, Terra implements, and selected high-risk work can use one Claude review. Includes a localhost dashboard; deploy is separately gated. |
| [pipeline](pipeline/) | `/pipeline` | `$pipeline` | Standard delivery pipeline for non-trivial work: coverage matrix (security/risk/review/tests/docs), adaptive routing, verification gates, PR-ready output. Routes real implementation into `orchestrate`. |
| [debug](debug/) | `/debug` | `$systematic-debugging` | Evidence-driven debugging. Hard bugs escalate to a dual-brain **council**: Claude + Codex research independently, hypotheses get falsified, candidate fixes race in disposable worktrees. Token-conscious, with a usage report. |
| [critique](critique/) | `/critique` | `$critique` | Fair-but-rigorous critical-friend pass on an idea/plan/prompt/architecture before you commit — steelman, challenge, calibrated verdict. |
| [autoreview](autoreview/) | — | `$autoreview` | One model-free local review pass for FAST changes or explicit self-review. Skips itself when a fresh Sol, Claude, or security reviewer already owns the target. |
| [security-review](security-review/) | — | `$security-review` | Proportional router for inline checks, targeted threat modeling, high-risk Codex Security diff scans, and optional Opus second opinions. |
| [chief-of-staff](chief-of-staff/) | `/chief-of-staff` | (Claude-only) | One chat orchestrates the session: decompose into parallel workstreams, delegate to background subagents, re-command mid-flight, route implementation into `orchestrate`, synthesize one answer. |

## Install a skill

Quickest — this repo is a Claude Code **plugin marketplace** (skill-only installs, no clone needed):

```
/plugin marketplace add Christoffer91/ai-coding-skills
/plugin install orchestrate@ai-coding-skills
/plugin install pipeline@ai-coding-skills
```

For orchestrate's full runtime (localhost dashboard, headless driver, Codex-side skill) clone and run the installer — it asks about each optional layer, all defaulting to No; each skill folder has its own `README.md`:

```bash
cd orchestrate && ./install.sh        # Claude skill + dashboard + Codex skill and six agent profiles
```

For skills without an installer, copy the subtree you want:

```bash
cp -R pipeline/claude/skills/pipeline ~/.claude/skills/pipeline
cp -R pipeline/codex/skills/pipeline  ~/.codex/skills/pipeline
cp -R autoreview/codex/skills/autoreview ~/.codex/skills/autoreview
cp -R security-review/codex/skills/security-review ~/.codex/skills/security-review
```

## Contributing / adding a skill (keep it clean)

Only **genericized** skills go here — no personal names, emails, absolute home paths, private repo
names, org/cloud IDs, account details, run records, or personal memory-system wiring. The public GitHub
owner appears only where an install command requires the repository address. Keep personal,
config-wired variants in a private source repository. New skills follow the same shape:
`<skill>/claude/skills/<skill>/`, `<skill>/codex/skills/<skill>/`, shared runtime at the skill root.

Before committing, run the guard:
```bash
./scan-pii.sh                       # scans for home paths + emails
PII_EXTRA='yourname|your-handle|private-repo' ./scan-pii.sh   # add your own tokens
```

## License
MIT — see [LICENSE](LICENSE).
