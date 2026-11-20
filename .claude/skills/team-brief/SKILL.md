---
name: team-brief
description: Spec-first delegation and independent verification for building an app or feature with sub-agents (Claude subagents or Codex). Use when a request is vague ("make me an app that…"), spans several files or workers, or when a fix keeps failing. Covers clarifying questions, docs/spec.md and docs/tasks.md, delegation prompts, cross-review, stop conditions and the final report.
---

# team-brief: spec → split → delegate → verify independently

Source idea: an article on running Claude Code as the "front desk" and Codex
(or other agents) as implementers/reviewers, plus the aws-samples agent-team
repos. Adapted here as a general workflow.

## 1. Clarify before building
- Do not start implementing a vague request. Turn unknowns into questions the
  user can answer, **one decision at a time**, each with: the options, the
  user-visible impact of each, and a recommendation with a short reason.
- Surface decisions that change architecture early (e.g. "same browser only"
  vs "sync across phone and PC" for storage). Never pick one silently.
- If the user already said "no approval needed", make the call yourself, using the
  recommended option, and record it in the spec as an assumption.

## 2. Write the spec (docs/spec.md)
- Scope **in** and scope **out** (e.g. out: login, multi-device sync, public deploy, real customer data).
- Acceptance criteria written as observable behavior, never "easy to use":
  "can register an item", "sorted by due date", "empty submit shows the reason",
  "data survives reload".
- Edge rules decided up front: tie-break order, required vs optional fields,
  date/timezone semantics.
- Separate **undecided** items: mark which block implementation and which can
  proceed on a provisional default. Never write an undecided item as decided.

## 3. Split the work (docs/tasks.md)
Each task states: files it owns, prerequisite tasks, how to verify, what to return.
- Fix shared interfaces first (field names, data shape, function signatures).
  Changes to shared parts go back to the coordinator, never decided by one worker.
- Never plan two workers editing the same file at once. One worker builds the scaffold;
  commit it before fanning out.
- Choose the mode per task: solo (small, one owner) / second opinion (review) /
  parallel (truly independent). Don't run heavy multi-agent review on doc typos.

## 3b. Running workers in parallel
- One isolated workspace per parallel worker: a git worktree/branch per session (Claude Code
  desktop parallel sessions or `isolation: "worktree"` subagents). No two workers on the same files.
- Protect the coordinator's context: send broad searches, dependency analysis and test/fix
  iterations to subagents and keep only their conclusions. The main thread keeps summaries
  and decisions only.
- Side questions mid-run go to a side channel (`/btw` in Claude Code) so the main plan isn't
  derailed.
- Keep parallelism small (≈ up to 4 workers) and only for truly independent tasks. The human
  reviews diffs of sessions that reach "needs input" or "completed", then integrates and
  re-runs all tests.
- What makes any agent tool work is the same everywhere: a clear design hand-off, the right
  files and rules to read, and a self-running mechanism with verification. Don't chase tool
  features at the expense of that.

## 4. Delegation prompt template
```
Read docs/spec.md and docs/tasks.md. Implement only <task>, touching only <files>.
Do not revert others' changes, read secrets, or publish anything.
If a spec change or another owner's file is needed, stop and report.
Return: changed files, commands run, test results, unverified items.
```
- For investigation-only work say explicitly "read-only, change no files".
  (Codex `/codex:rescue` defaults to write access unless told otherwise.)
- Instructions are not permissions: a role named "reviewer" is not sandboxed.
  Subagents inherit the parent's permissions.
- If the requested agent/tool is unavailable, report it; don't silently switch.

## 5. Verify with a different agent
- Reviewer gets the human-confirmed spec + the actual diff, **not** the
  implementer's self-assessment ("it's fixed now").
- Ask it to separate: reproduced problems / plausible concerns / could not verify.
  Review finds problems, it does not fix them. Fixes are a separate request.
- Cross the pair: Claude implemented → other agent reviews, and vice versa.
- For design-assumption risk, use an adversarial review ("does a save failure show as
  success? do two tabs clobber each other?").
- Each finding: which acceptance criterion, user impact, how to confirm. Anything
  needing a spec change goes back to the human as options.

## 6. Tests
- Keep "agent drives a browser" separate from "repeatable test" (e.g. Playwright Test).
- Zero tests found or all skipped is **not** a pass.
- Never delete/weaken a test or change acceptance criteria to go green. Decide
  against the spec whether the app or the test is wrong.
- Re-run all tests after integrating worktrees/branches.

## 7. Stop conditions
- Same bug, two fix attempts, still failing → stop changing code. Write a handoff:
  what was tried, what changed, remaining symptom, decision needed. Don't widen
  scope. Hand to a different agent with fresh context.
- Cancel background jobs you no longer need and confirm they stopped.
- Don't enable automatic review loops (e.g. Codex review gate) while unattended: they can
  burn quota in long fix ping-pong.

## 8. Final report (four items, not a diary)
1. How to run it  2. Verified behavior  3. Remaining limits  4. Next fix candidates

Measure "fast" by: times the user had to re-explain, time spent integrating/fixing,
defects left against acceptance criteria, not by generation time.
