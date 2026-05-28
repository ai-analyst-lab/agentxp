# AgentXP slash command vocabulary

Seven slash commands. Each invokes a skill at `.claude/skills/<name>/SKILL.md`.

| Command | When to use | Skill |
|---|---|---|
| `/experiment` | Run a full 11-stage experiment | experiment |
| `/profile` | Inspect a dataset before designing a test | profile |
| `/connect-data` | Wire a warehouse (DuckDB in v0.1; Snowflake/BigQuery in v0.1.1) | connect-data |
| `/resume` | Resume an interrupted experiment | resume |
| `/audit` | Replay the decision chain | audit |
| `/list` | Show experiments in this project | list |
| `/unlock` | Release a stale project lock | unlock |

## You can also describe what you want in plain English

The slash commands are shortcuts. Claude routes plain-English questions to the right command:

- "I want to test the checkout button" → `/experiment`
- "Look at this dataset" → `/profile`
- "Why did exp_007 fail?" → `/audit exp_007`
- "I'm stuck — what now?" → `/resume`
- "Show me what's running" → `/list`
- "The lock is stuck" → `/unlock`
- "Connect my warehouse" → `/connect-data`

## How the commands compose

A typical first session runs `/connect-data` once to wire a source, then `/profile` to inspect the dataset, then `/experiment` to traverse the eleven stages. Later sessions use `/list` to recall what was run, `/audit` to replay decisions, and `/resume` when a prior run was interrupted. The `/unlock` command is reserved for the rare case where a lockfile outlives the process that wrote it.

Every command writes to the same `experiments/<exp_id>/` directory layout: `state.yaml` for the current stage, `log.jsonl` for the audit chain, `bundles/` for inter-stage data, and `queries/` for dispatched SQL. The vocabulary is deliberately closed; new behaviour is added by extending an existing skill rather than by minting a new command.

## For top-level orientation

See [CLAUDE.md](../../CLAUDE.md) for the 11-stage journey, the 13 agents, the audit chain, and the closed-set vocabulary.

## For per-skill detail

Each `.claude/skills/<name>/SKILL.md` documents the per-command workflow, the agent dispatch table, and the bundle schema for that stage.
