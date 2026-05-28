---
description: Run a full AgentXP experiment end to end through the 11-stage pipeline.
argument-hint: "[--data PATH] [--brief PATH] [--from-stage STAGE] [--resume EXP_ID]"
---

# /experiment

Use this command to run a complete experiment in the current project. The pipeline traverses eleven stages from intent capture through verdict and readout: intent, dataset profile, brief, design, power, allocation, execution, monitoring, analysis, decision, and writeup. At each stage the orchestrator persists state to `experiments/<exp_id>/` and writes an entry to `log.jsonl`. After the final stage the user receives a verdict and a readout suitable for sharing.

The default entry point asks the user what they want to test. Optional flags shift the entry point: `--data PATH` begins at Stage 0 (dataset profiling); `--brief PATH` begins at Stage 1 with a prepared brief; `--from-stage STAGE` re-enters the pipeline at a named stage; `--resume EXP_ID` delegates to the resume skill for an existing experiment.

This command invokes the `experiment` skill at `.claude/skills/experiment/SKILL.md`. The skill orchestrates the eleven stages, the thirteen agents, and the audit chain that records every decision in the project log.

For the full command vocabulary, see [.claude/commands/README.md](README.md).
For top-level orientation about AgentXP, see [CLAUDE.md](../../CLAUDE.md).
