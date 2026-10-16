# Working notes for Claude

## Learned practices (from "Claude×Codex agent design" article, 2026-10)
- For multi-step builds, delegation, or stuck fixes, follow `.claude/skills/team-brief/SKILL.md`.
- Spec lives in one file (`docs/spec.md`). CLAUDE.md and AGENTS.md (Codex) only point to it
  plus "no changes outside the request". Never duplicate the spec into both, because one copy goes stale.
- Acceptance criteria = observable behavior. Unknowns are asked as one decision at a time
  with impact + recommendation.
- Verification is done by a different agent from the implementer, given spec + diff, not the
  implementer's claims.
- Two failed fixes on the same bug → stop, write a handoff, switch agent.
- Prompt instructions ≠ permissions. Check real sandbox/permission settings; review hooks
  before enabling them; deletion, publishing and paid actions need separate approval.

## Codex plugin for Claude Code (openai/codex-plugin-cc), reference
- Install: `/plugin marketplace add openai/codex-plugin-cc`, `/plugin install codex@openai-codex`,
  `/reload-plugins`, `/codex:setup` (auth: `codex login`). Uses Codex's own quota, not Claude's.
- `/codex:review [--base main] [--background]`: plain review, takes no focus text.
- `/codex:adversarial-review "<risk to probe>"`: challenges design assumptions; focus text allowed.
- `/codex:rescue --fresh|--resume "<task>"`: delegate investigation/fix. Writable unless told read-only.
- `/codex:transfer`: move the conversation into a resumable Codex thread (files/auth/app state are not moved).
- `/codex:status`, `/codex:result <job-id>`, `/codex:cancel`. Pass the job ID when several jobs run.
- Review gate (`/codex:setup --enable-review-gate`) auto-reviews every Claude stop. Risk of quota-burning loops; off by default.
- Custom Codex roles: `.codex/agents/<name>.toml` (name, description, developer_instructions).
  Leave model unset so it inherits. Hard-coded models break when retired
  (GPT-5.5 left ChatGPT-auth Codex on 2026-10-15 JST).
