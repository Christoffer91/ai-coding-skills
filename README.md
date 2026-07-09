# claude-skills

A small collection of portable **Claude Code / Codex** skills. Each top-level folder is a self-contained skill you can drop into `~/.claude/skills`. No personal config, paths, or credentials — bring your own logins.

## Skills
| Skill | What it does |
|---|---|
| [orchestrate](orchestrate/) | Dual-brain plan → execute → review → ship loop: **Claude** plans & reviews the PR, **OpenAI Codex CLI (gpt-5.6-sol)** critiques the plan, writes the code, opens the PR, and applies review edits. Deploy is human-gated. |

## Install a skill
Each skill folder has its own `README.md` and `install.sh`. For example:
```bash
cd orchestrate && ./install.sh
```

## Contributing / adding a skill (keep it clean)
Only **genericized** skills go here — no usernames, emails, absolute home paths, private repo names, org/cloud IDs, or personal memory-system wiring. Keep your personal, config-wired versions in a private dotfiles repo.

Before committing, run the guard:
```bash
./scan-pii.sh                       # scans for home paths + emails
PII_EXTRA='yourname|your-handle|private-repo' ./scan-pii.sh   # add your own tokens
```

## License
MIT — see [LICENSE](LICENSE).
