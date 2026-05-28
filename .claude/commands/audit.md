---
description: Replay the decision chain for any experiment in the project.
argument-hint: "<exp_id> [--diff OTHER_EXP_ID] [--html [--out PATH]]"
---

# /audit

Use this command to replay the decision chain for any experiment in the project. It reads `experiments/<exp_id>/log.jsonl`, the persisted decisions, the input and output bundles, and the SQL queries dispatched during execution. The default rendering is a text summary of the thirteen-event chain, showing which agent acted at each stage, what was decided, and what was written.

The `--diff OTHER_EXP_ID` flag produces a pairwise diff against a second experiment, useful when a follow-up run produced a different verdict and the user wants to locate the divergent stage. The `--html` flag emits a self-contained HTML report; `--out PATH` controls the destination. Plain-English questions also route here: "Why did exp_007 halt at Stage 5?" reaches the same skill.

This command invokes the `audit` skill at `.claude/skills/audit/SKILL.md`. The skill orchestrates the log replay, the bundle reconciliation, and the chosen rendering.

For the full command vocabulary, see [.claude/commands/README.md](README.md).
For top-level orientation about AgentXP, see [CLAUDE.md](../../CLAUDE.md).
