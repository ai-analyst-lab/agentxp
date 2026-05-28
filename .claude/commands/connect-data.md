---
description: Connect a warehouse for SQL execution. Snowflake and BigQuery wizards ship in v0.1.1.
argument-hint: "<warehouse: duckdb | snowflake | bigquery>"
---

# /connect-data

Use this command to wire a data source for SQL execution. The DuckDB path is supported in v0.1: the skill prompts for a local file path, validates that the file exists and opens cleanly, and records the connection in the project configuration so subsequent stages can dispatch queries against it.

The Snowflake and BigQuery wizards ship in v0.1.1. When the user selects one of these warehouses today, the skill explains the timeline and suggests pointing at a local DuckDB file in the meantime, which preserves the full pipeline behaviour without external credentials.

This command invokes the `connect-data` skill at `.claude/skills/connect-data/SKILL.md`. The skill orchestrates the warehouse selection, the credential or path prompt, and the configuration write.

For the full command vocabulary, see [.claude/commands/README.md](README.md).
For top-level orientation about AgentXP, see [CLAUDE.md](../../CLAUDE.md).
