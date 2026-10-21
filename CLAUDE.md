# Working notes for Claude

## When the user sends articles/posts to "learn"
- The user delegates reading entirely and won't read them. Fetch everything, including
  threads, replies, quoted articles and media.
- Save only what changes behavior or adds new facts (skills/CLAUDE.md). Don't re-save what
  is already covered.
- Report in Japanese, tersely, sorted into: new facts / what changes in my behavior /
  discounted as promo or unverified / nothing new. Say plainly when an article adds nothing.

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

## Learned practices (from "Obsidian × dots" article, 2026-10)
- For turning notes/knowledge bases into articles, courses or proposals, follow
  `.claude/skills/knowledge-vault/SKILL.md`.
- Keep source material, AI drafts and human-adopted content separate; AI output never becomes
  a "source" without a link and checked date. Track published date vs checked date separately.
- Report which files were actually read this run; re-read files after saving them.
- Delegated or scheduled tasks don't inherit the conversation, so pass rules and paths explicitly.
  Try once manually before scheduling (timezone, end date, notification, output location).
- "No record" ≠ "not done": flag as a check candidate, don't assert.

## Learned practices (X posts, 2026-10-20)
- Autonomous/long-running or "keep going until it works" tasks: follow
  `.claude/skills/verified-loop/SKILL.md` (external verifier, state log, budget and stop
  conditions, commit per kept step; judge by cost per accepted result).
- Parallel sessions: one worktree per worker, subagents to keep the main context clean,
  `/btw` for side questions (see team-brief §3b).
- 3D work: build scenes as parameterized Blender Python scripts
  (`.claude/skills/blender-scripting/SKILL.md`). Render a preview and look at it before claiming success.
- Usage limits hit quickly → run `/usage` first (shows share used by Skills, subagents,
  plugins and MCP servers, plus recurring jobs like `/loop` with run counts and tokens per run).
  Disable unused MCP servers via `/mcp` and stop forgotten loops or background jobs before
  micro-optimizing prompts.

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
