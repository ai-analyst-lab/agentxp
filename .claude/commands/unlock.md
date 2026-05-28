---
description: Force-release a stale project lock at .state.lock.
argument-hint: "<exp_id> [--force]"
---

# /unlock

Use this command when an experiment cannot proceed because `.state.lock` is held by a process that is no longer running. The skill reads the lockfile, extracts the recorded PID, and tests liveness via `os.kill(pid, 0)`. If the process is dead the lock is released. If the process is alive the skill refuses unless `--force` is supplied, on the assumption that an active run should not be displaced without an explicit override.

Every release emits a `lock.stale_reclaimed` event to the audit chain so the recovery is visible in subsequent `/audit` runs. Direct deletion of `.state.lock` via `rm` is discouraged because it orphans the audit row and leaves no record of who reclaimed the lock or when.

This command invokes the `unlock` skill at `.claude/skills/unlock/SKILL.md`. The skill orchestrates the liveness probe, the conditional release, and the audit emission.

For the full command vocabulary, see [.claude/commands/README.md](README.md).
For top-level orientation about AgentXP, see [CLAUDE.md](../../CLAUDE.md).
