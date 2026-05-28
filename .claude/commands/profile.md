---
description: Profile a dataset (Stage 0 only). Surfaces column structure, null rates, and data-quality flags.
argument-hint: "<path-to-data-file>"
---

# /profile

Use this command to inspect a dataset before designing a test. It runs Stage 0 of the pipeline in isolation: a DuckDB `SUMMARIZE` over the file followed by the profiler agent, which produces a semantic interpretation pass with a column table annotated with a short `my read` for each field. The result is written to `bundles/profiler.out.yaml` and printed to the terminal.

The profiler surfaces the HG-D4 heuristic flags during the pass: mixed timestamp formats within a single column, and identifier-shaped columns whose null rate exceeds the threshold for a primary key candidate. These flags are not blockers; the user decides whether to repair the data, narrow the scope, or proceed.

This command invokes the `profile` skill at `.claude/skills/profile/SKILL.md`. The skill orchestrates the SUMMARIZE pass, the profiler agent dispatch, and the bundle write.

For the full command vocabulary, see [.claude/commands/README.md](README.md).
For top-level orientation about AgentXP, see [CLAUDE.md](../../CLAUDE.md).
