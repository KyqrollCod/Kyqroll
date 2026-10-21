---
name: verified-loop
description: Design and run an autonomous improve-and-check loop (goal → attempt → objective verification → feedback → retry) for fixing failing tests, optimizing a measurable metric, routine maintenance, or long-running multi-day agent work (including one agent supervising another, e.g. Codex driving Claude Code). Use when the user wants work to continue without step-by-step instructions, or asks for a "loop", "self-healing", or "keep going until it passes".
---

# verified-loop: a loop is only as good as its verifier

Sources: "How to Build AI Loops That Are Replacing Prompt Engineering" (Karpathy's
autoresearch: ~700 experiments in 2 days, ~20 kept), and the "Codex drives Claude Code
for days" pattern. A scheduled prompt is not a loop. A loop has
**Discover → Plan → Execute → Verify → Iterate**, and three parts are non-negotiable:

| Part | Without it |
|---|---|
| **Verifier**: objective check (tests, compiler, benchmark, validation script) | the agent confidently repeats mistakes |
| **Memory**: log of attempts, failures, what improved | it rediscovers the same failures |
| **Stop conditions**: goal reached, or a hard limit hit | it burns tokens/compute indefinitely |

## Before starting, write these down (ask only if truly unknown)
1. **Goal** as a measurable condition (`verify.sh` exits 0; metric < X).
2. **Verifier** the agent cannot edit. The agent never judges its own success; the
   verifier does. Two agents agreeing is not proof. Run the tests or benchmark.
3. **Allowed edit surface** (e.g. only `train.py` / `src/`). Evaluation code, tests and
   acceptance criteria are off limits ("improve the model without changing evaluation").
4. **Budget**: max attempts, wall-clock/timeouts, token or cost ceiling, and a
   repeated-failure detector (same error twice → change approach or stop; see team-brief).
5. **State file** (e.g. `loop-log.md` / JSON): attempt #, hypothesis, change, verifier
   result, kept/reverted. Read it at the start of every iteration.
6. **Checkpoints**: commit each kept improvement so any step can be rolled back;
   revert rejected attempts.

## Minimal three-file layout
- `CLAUDE.md` / `AGENTS.md`: objective, conventions, permitted operations, restrictions.
- `loop.py` (or a Workflow/script): calls the agent, enforces limits, records state.
- `verify.sh`: the commands that decide success.
```python
for attempt in range(MAX_ATTEMPTS):
    agent.run(goal, context=read_state())
    result = verify()            # external, deterministic
    record(attempt, result)      # memory
    if result.passed: commit(); break
    if repeated_failure(result): stop_and_handoff(); break
    revert_uncommitted()
```
Get **one supervised run** producing acceptable results before attaching it to a schedule,
a CI event, or a long unattended run.

## Patterns
- **Self-healing repo**: CI fails → agent gets logs + context → fix → re-run tests →
  on pass open a PR with evidence → **human reviews before merge**.
- **Metric search** (perf, model quality): keep a change only if correctness holds and the
  measured gain is real and reproducible. Otherwise reject.
- **Supervisor/implementer for multi-day work** (e.g. Codex manages, Claude Code
  implements): the supervisor splits tasks, the implementer builds, the supervisor checks
  against the verifier and sends fixes, then moves to the next task. Add a commit per
  milestone, define where a human checks in (milestones, spec changes, anything
  irreversible), and watch cost ("check the bill before the code"). Each tool bills its
  own quota.

## Risks to manage
- **Uncontrolled execution**: hard budgets and attempt caps, cancel leftover background jobs.
- **Comprehension debt**: changes land faster than people understand them. Keep loops on
  narrow, verifiable tasks. Summarize what changed and why for the human. Auth, payments,
  critical infra and irreversible operations stay under human judgment.
- Passing tests ≠ maintainable or secure. Zero or skipped tests ≠ pass. Never weaken the
  verifier to finish.

## Metric
Judge by **cost per accepted result** (time + compute + human review per verified, useful
change), not by agents running, tokens spent or PRs opened. Start from one annoying recurring
task with an objective success definition → make it reliable → add memory → enforce
budget → automate → expand.
