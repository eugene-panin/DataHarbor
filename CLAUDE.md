# Claude Code

Agent contract for this repo is **agent-agnostic** and lives in [`AGENTS.md`](AGENTS.md), not in Cursor-only files.

1. Read **AGENTS.md §0** (skill routing).
2. Load **one** matching skill from `.agents/skills/<name>/SKILL.md`.
3. Optional: `harbor skill install` copies those skills into `~/.claude/skills`.

Do not treat `.cursor/rules/` as source of truth.
