---
description: Show all experiments in this project.
argument-hint: "[--status STAGE] [--since DAYS] [--json]"
---

# /list

Use this command to enumerate the experiments in the current project. The skill walks `experiments/*/state.yaml` and renders a markdown table by default: experiment id, current stage, last-modified timestamp, and a one-line intent summary. The `--json` flag emits the same data as machine-readable JSON for downstream tooling.

Two filters narrow the result. `--status STAGE` restricts the listing to experiments whose current stage matches the named value. `--since DAYS` restricts to experiments modified within the trailing window. When the project contains no experiments the skill emits a short message pointing the user at `/experiment` to begin a new run.

This command invokes the `list` skill at `.claude/skills/list/SKILL.md`. The skill orchestrates the directory walk, the filters, and the renderer.

For the full command vocabulary, see [.claude/commands/README.md](README.md).
For top-level orientation about AgentXP, see [CLAUDE.md](../../CLAUDE.md).
