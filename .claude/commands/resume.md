---
description: Resume an interrupted experiment. Classifies into one of 8 recovery cases per §10.6.
argument-hint: "<exp_id> [--force]"
---

# /resume

Use this command when an experiment was interrupted and the user wants to continue. The skill reads `state.yaml`, `log.jsonl`, and `.state.lock` for the named experiment and classifies the interruption into one of the eight recovery cases enumerated in §10.6 of the specification. Each case has a matching dialog that explains the situation and the proposed next action.

Case 1 (clean resume from the last completed stage) proceeds automatically. Cases 2 through 7 require user confirmation before any state mutation. Case 8, which involves a schema migration on the persisted state file, requires `--force` to acknowledge that the migration is irreversible without a backup.

This command invokes the `resume` skill at `.claude/skills/resume/SKILL.md`. The skill orchestrates the recovery classification, the dialog selection, and the handoff back to the experiment pipeline.

For the full command vocabulary, see [.claude/commands/README.md](README.md).
For top-level orientation about AgentXP, see [CLAUDE.md](../../CLAUDE.md).
