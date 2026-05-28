# CLAUDE.md — AgentXP

## 1. Identity and one-line journey

AgentXP is an open-source system for the design and analysis of controlled experiments, opened inside Claude Code and driven through plain-English conversation. A pipeline of thirteen LLM agents carries an experiment from data profiling through a pre-registered brief, sample-ratio monitoring, statistical analysis, and a final readout, with every choice committed to an append-only audit log that any reviewer can replay.

The canonical journey is eleven stages: `data_loaded` (0), `semantic_models_drafted` (0.5), `metrics_bootstrapped` (0.75), `intent_captured` (1), `hypothesis_drafted` (2), `brief_drafted` (3) — with a `brief_contradicted` (3b) substate when the consistency judge flags a hypothesis-vs-brief mismatch — `data_plan_confirmed` (4), `monitor` (5), `analyze` (6), `interpret` (7), and `readout` (8). Stages 0 through 0.75 run once per dataset; stages 1 through 8 run per experiment.

The architecture has six layers — warehouse, semantic, metric, assignment, experiment, analysis, readout — and a single orchestration chokepoint (`agentxp.orchestrator.store.OrchestratorStore.advance`) through which every stage transition flows. Statistical work is handled by deterministic Python in `agentxp.stats.*`; agents handle only the steps that require judgment, with their context strictly bounded by the bundle they were dispatched with. The audit guarantee derives from this isolation: two reviewers running the same audit log against the same project YAMLs reach the same answer.

---

## 2. What can I do here?

When the user opens this repository in Claude Code, the canonical first-turn answer is a list of entry points.

- `/experiment` — full eleven-stage walk from intent through verdict
- `/profile <path>` — Stage 0 only; inspect a dataset and write `bundles/profiler.out.yaml`
- `/connect-data <warehouse>` — wire a Snowflake or BigQuery connection (DuckDB ships in v0.1; Snowflake and BigQuery wizards land in v0.1.1)
- `/resume <exp_id>` — re-enter an interrupted experiment via the eight-case classifier
- `/audit <exp_id>` — replay the decision chain; supports `--diff` and `--html`
- `/list` — show experiments in this project (supports `--status`, `--since`, `--json`)
- `/unlock <exp_id>` — force-release a stale `.state.lock` whose holder PID is dead

Or just describe what you want in plain English. The router maps natural-language phrases to the right command using the intent table in §4. For instance, "I want to test whether the new checkout button improves completion; data at ~/data/checkout.parquet" routes to `/experiment --data`, while "why did exp_007 halt at Stage 5?" routes to `/audit exp_007`.

---

## 3. Session bootstrap

On the first user turn in a project, before responding to substantive intent, scan for existing state.

1. Run `ls experiments/*/state.yaml` (or equivalent) to enumerate in-progress experiments.
2. If the directory is non-empty, surface a short list: for each experiment, read `state.yaml` and report `experiment_id`, `current_stage`, and `pending_decision.kind` if set. Ask: "Resume which?" The user picks one (or says "new"), at which point routing proceeds via `/resume <chosen_id>` or `/experiment`.
3. If the directory is empty, proceed directly to `/experiment` intent capture.

The bootstrap is what prevents Claude from re-running completed stages or scaffolding a duplicate experiment when a prior session was interrupted. Never bootstrap directly into Stage 0 when `state.yaml` exists; always route through `/resume` so the eight-case classifier in `agentxp/cli/resume.py` decides whether to re-present a gate, retry a dispatch, or surface a stale-lock recovery.

The eight cases the resume classifier recognizes — referenced from §10.6 of the plan and from `agentxp/cli/resume.py`:

- Case 1 — `RESUME_AT_CLEAN_END`: terminal no-op. The experiment finished; nothing to resume.
- Case 2 — `RESUME_AT_PENDING_DECISION`: re-render the gate dialog. The previous session set `pending_decision` and exited; the user resolves it now.
- Case 3 — `RESUME_AT_MID_COMMIT`: SIGINT arrived inside `_commit_stage`. The commit either completed (last two events are `stage.committed` + `gate.blocked(reason="user_interrupt")`) or did not (no terminal `stage.committed` for the in-flight stage); the classifier picks accordingly.
- Case 4 — `RESUME_AT_AGENT_DISPATCH`: the LLM call was interrupted. The classifier finds an orphan `agent.dispatched` with no paired `agent.completed`. It asks permission to retry the dispatch.
- Case 5 — `RESUME_AT_QUERY_DISPATCH`: the warehouse round-trip was interrupted. Same shape as Case 4 but on `query.proposed` without `query.executed` or `query.failed`.
- Case 6 — `RESUME_AT_STAGE_3B`: the brief-contradiction gate was open. Re-present the `Stage3bChoice = "r" | "e" | "o"` dialog with the consistency judge's report attached.
- Case 7 — `RESUME_AT_GATE_BLOCKED`: a failure-mode gate is in place. Re-check the precondition (disk space, auth, project lock) and either clear the gate or re-emit it.
- Case 8 — `RESUME_AT_UNRECOVERABLE`: schema-version mismatch, corruption, or `validate_chain` violation. The user is told to file a bug; manual editing of `decisions/*.yaml` or `conversation.jsonl` is unsupported.

When the resume classifier reports a stale lock — `.state.lock` carries a PID that `os.kill(pid, 0)` says is dead — it reclaims the lock automatically and emits `stage.committed(metadata.subtype="lock.stale_reclaimed")`. If the PID is alive but on a different machine (the lock's `hostname` field differs from the current host), the user is told to either wait or invoke `/unlock <exp_id>` as an explicit override. Never `rm` the lock file directly; that orphans the audit row.

---

## 4. The eleven-stage journey

The canonical stage table is reproduced from `OPENXP_V01_PLAN.md` §3 with an added "user intent" prefix column that maps natural-language triggers to the stage and agent set Claude should dispatch.

| # | Stage | User-intent prefix | Routes to | Agent(s) | Reads | Writes | Human gate | Events |
|---|-------|--------------------|-----------|----------|-------|--------|------------|--------|
| 0 | `data_loaded` | "I have data at X" / "look at this dataset" | `/profile` or `/experiment --data` | `profiler` | source path or connection | `data_plan.yaml` (partial) + `bundles/profiler.out.yaml` | none | `stage.entered`, `stage.committed` |
| 0.5 | `semantic_models_drafted` | "define entities" / "what are the users in this data" | (stage 0.5 of `/experiment`) | `semantic_modeler` | `ProfileReport` JSON | `{project}/semantic_models/<entity>.yaml` + `state.yaml.semantic_models_refs` | `confirm_semantic_model` | `stage.committed` |
| 0.75 | `metrics_bootstrapped` | "set up metrics" / "what should I measure" | (stage 0.75) | `metric_drafter` | semantic models + `ProfileReport.suggestions` | `{project}/metrics/<name>.yaml` + `state.yaml.metrics_refs` | `confirm_metric` | `stage.committed` |
| 1 | `intent_captured` | "I want to test X" | `/experiment` | `designer.elicitor` | user prose only | `state.yaml.intent` + a turn appended to `conversation.jsonl` | none | `stage.entered` |
| 2 | `hypothesis_drafted` | "draft a hypothesis" | (stage 2) | `designer.elicitor` | intent + prior turns | `state.yaml.hypothesis` + `decisions/02-hypothesis.yaml` | none in v0.1 (`confirm_hypothesis` reserved, folded into `confirm_brief`) | `stage.committed` |
| 3 | `brief_drafted` | "draft a brief" | (stage 3) | `designer.drafter` then `consistency_judge` | hypothesis, metrics, semantic models, segment turns | `experiment.yaml` (status=`DESIGNING`) + `decisions/03-brief.yaml` | `confirm_brief` | `stage.committed` with `metadata.dag_transition: {from: null, to: DESIGNING}` |
| 3b | `brief_contradicted` | (consequence of stage 3) | (substate of stage 3) | `designer.editor` if `e` | brief, hypothesis, judge report | `state.yaml.pending_decision` + `decisions/03b-contradiction.yaml` | `brief_contradiction` with `Stage3bChoice = "r" \| "e" \| "o"` | `gate.blocked`, `gate.resolved` |
| 4 | `data_plan_confirmed` | "bind the data plan" | (stage 4) | `designer.drafter` (+ `metric_drafter` for inline assignment synthesis) | brief, semantic models, assignment, metrics | full `data_plan.yaml`, `DESIGNING→POWERED` | `confirm_data_plan` then `confirm_cohort` then `confirm_assignment` | `stage.committed` |
| 5 | `monitor` | "build cohorts" / "check SRM" | (stage 5) | `sql_query_writer` then `monitor` | observations via SQL, brief | `analyses/{ts}.json` (pre-analysis), `bundles/monitor.out.yaml`, `queries/{ulid}.yaml` | `confirm_query` per query; `srm_override` if χ² yellow | `stage.committed` with dag `POWERED→COLLECTING→ANALYZING`, or `gate.blocked(kind="srm_override")` |
| 6 | `analyze` | "analyze the results" | (stage 6) | `sql_query_writer` then `analyzer` | brief, observations, monitor output | `analyses/{ts}.json` (full), `queries/*.yaml` | `confirm_query` per query | `stage.committed` |
| 7 | `interpret` | "what does this mean" | (stage 7) | `interpreter` | latest analysis, brief decision rules | `interpretation.json` (8-step tree, `step_fired`) | none | `stage.committed` with dag `ANALYZING→INTERPRETED` |
| 8 | `readout` | "write the readout" | (stage 8) | `readout` | brief, analysis, interpretation | `report.md` + `report.json` | `confirm_readout` | `stage.committed` with dag `INTERPRETED→REPORTED` |

DAG transitions are recorded in `stage.committed.metadata.dag_transition: {from, to}`. There is no separate `experiment_status_changed` event. Sub-event variations — cache hits, correction attempts, retries, auth-expired errors, disk-full halts — ride on `metadata.subtype` (see §9 and §10).

### Plan-execution shape (which stages run when)

The full eleven-stage walk is the canonical path, but not every entry point starts at Stage 0. Five execution plans cover the common cases; the orchestrator scaffolds `state.yaml` accordingly.

| Plan | Use when | Stages that run |
|------|----------|-----------------|
| `full` | hypothesis through verdict, end to end | 0 through 8 (skips 0.5 and 0.75 if the project already has semantic models and metrics for the source) |
| `from_brief` | brief already exists; analyze the data | 4 through 8 (assumes a confirmed brief at `experiments/<exp_id>/experiment.yaml`) |
| `from_data` | data already loaded; design from there | 1 through 8 |
| `profile_only` | inspect a dataset without designing | 0 only (no `state.yaml` is written) |
| `audit` | replay a past run | none; the audit CLI walks `log.jsonl` |

The orchestrator infers the plan from the slash command arguments. `/experiment --data <path>` selects `from_data`; `/experiment --from-brief <path>` selects `from_brief`; `/profile <path>` selects `profile_only`; a bare `/experiment` selects `full`. The plan is recorded in `state.yaml.session.last_action_metadata.plan` so the audit replay can reconstruct what was intended.

### Conversation log conventions

Every user prose turn is appended to `experiments/<exp_id>/conversation.jsonl` via `ConversationStore.append_turn(...)`. The turn carries a `turn_id` (ULID), a `role` (`user` or `system`), a `content` block, and a `timestamp`. Bundles reference a `through_turn_id` rather than embedding the full conversation; the `BundleStore.assemble` step rolls the most recent fifty turns into a `prior_turns_compressed` block per `OPENXP_V01_PLAN.md` §10.8.1. Agents see only the compressed view; the full log is for audit replay and for the PII redactor.

Before any user prose is appended to `conversation.jsonl` or written into a `decisions/*.yaml`, route it through `agentxp.audit.redactor.redact_pii(...)`. The redactor is the canonical entry point for the built-in PII pre-flight; downstream readers assume `conversation.jsonl` has already been redacted.

---

## 5. The thirteen agents

Every agent loads its system prompt from disk and runs against a bundle assembled by `BundleStore.assemble()`. The bundle is the agent's only context.

| Agent | Stage(s) | File path | Bundle in | Bundle out |
|-------|---------|-----------|-----------|------------|
| `profiler` | 0 | `agents/profiler.system.md` | `bundles/profiler.ctx.yaml` | `bundles/profiler.out.yaml` |
| `semantic_modeler` | 0.5 | `agents/semantic_modeler.system.md` | `bundles/semantic_modeler.ctx.yaml` | `bundles/semantic_modeler.out.yaml` |
| `metric_drafter` | 0.75, 4 | `agents/metric_drafter.system.md` | `bundles/metric_drafter.ctx.yaml` | `bundles/metric_drafter.out.yaml` |
| `designer.elicitor` | 1, 2, 3 | `agents/designer/elicitor.system.md` | `bundles/designer.elicitor.ctx.yaml` | `bundles/designer.elicitor.out.yaml` |
| `designer.drafter` | 3, 4 | `agents/designer/drafter.system.md` | `bundles/designer.drafter.ctx.yaml` | `bundles/designer.drafter.out.yaml` |
| `designer.editor` | 3, 4 edits | `agents/designer/editor.system.md` | `bundles/designer.editor.ctx.yaml` | `bundles/designer.editor.out.yaml` |
| `consistency_judge` | 3 → 3b | `agents/consistency_judge.system.md` | `bundles/consistency_judge.ctx.yaml` | `bundles/consistency_judge.out.yaml` |
| `sql_query_writer` | 0.5, 0.75, 5, 6 | `agents/sql_query_writer.system.md` | `bundles/sql_query_writer.ctx.yaml` | `bundles/sql_query_writer.out.yaml` |
| `sql_corrector` | any (on `query.failed`) | `agents/sql_corrector.system.md` | `bundles/sql_corrector.ctx.yaml` | `bundles/sql_corrector.out.yaml` |
| `monitor` | 5 | `agents/monitor.system.md` | `bundles/monitor.ctx.yaml` | `bundles/monitor.out.yaml` |
| `analyzer` | 6 | `agents/analyzer.system.md` | `bundles/analyzer.ctx.yaml` | `bundles/analyzer.out.yaml` |
| `interpreter` | 7 | `agents/interpreter.system.md` | `bundles/interpreter.ctx.yaml` | `bundles/interpreter.out.yaml` |
| `readout` | 8 | `agents/readout.system.md` | `bundles/readout.ctx.yaml` | `bundles/readout.out.yaml` |

**Dot-namespace resolution.** Agent names that contain a dot resolve to a nested file path: `designer.elicitor` is `agents/designer/elicitor.system.md`, `designer.drafter` is `agents/designer/drafter.system.md`, `designer.editor` is `agents/designer/editor.system.md`. All other agents are at `agents/<name>.system.md`. Bundle filenames preserve the dotted form (e.g., `bundles/designer.elicitor.ctx.yaml`).

**Model selection.** Every agent in v0.1 uses Opus 4.7 (`claude-opus-4-7`). No mixing across agents — voice consistency depends on a single model carrying every dialog.

**Voice samples.** Each agent has a sample dialog at `agents/fixtures/voice_samples/<agent>_sample.md`, authored before the prompt itself. These double as voice-CI smoke inputs.

---

## 6. Bundle convention

The bundle convention is the load-bearing axiom of the architecture. Read it carefully.

When `OrchestratorStore.advance` reaches a stage that requires an agent, it calls `BundleStore.assemble()` (in `agentxp/orchestrator/bundle.py`) to build the agent's context file at `bundles/<agent>.ctx.yaml`. The assembly step **copies** — does not reference — every project-level YAML the agent depends on (`{project}/semantic_models/*.yaml`, `{project}/fact_sources/*.yaml`, `{project}/metrics/*.yaml`, `{project}/assignments/*.yaml`) into the bundle directory. The SHA256 of each copied file is recorded in `bundles/<agent>.ctx.yaml.metadata.source_hashes`.

Once assembled, the bundle is the source of truth for that single agent invocation. If a parallel session edits a project YAML between bundle assembly and the dispatched agent's return, the in-flight agent still sees the version captured at assembly time. This eliminates a whole class of race conditions and is the substrate `validate_chain` Invariant 3 walks during commit.

The assembly runs under a shared (read) lock on `{project}/.agentxp/.project.lock`, which permits multiple concurrent assemblies but excludes any concurrent `metric_drafter` or `semantic_modeler` write.

Agents observe three constraints that follow from the bundle policy:

- Agents never read `state.yaml`.
- Agents never read `conversation.jsonl` directly. A compressed view of recent turns rides inside the bundle as `prior_turns_compressed`.
- Agents never read other agents' bundles.

The bundle is the agent's whole world. This is what makes two reviewers running the same audit log reach the same answer.

---

## 7. Stage commit recipe

There is one chokepoint and only one. Every stage transition flows through `OrchestratorStore.advance`. Never bypass it. Never mutate `state.yaml` directly — the SIGINT guard and `validate_chain` are what make the audit chain credible, and direct mutation strips both.

```python
from agentxp.orchestrator.store import OrchestratorStore

store = OrchestratorStore(project_root, exp_id)
store.advance(user_input=...)
# advance() internally:
#   1. resolves the current_stage from state.yaml
#   2. assembles bundles/{agent}.ctx.yaml via BundleStore.assemble()
#      (which COPIES project YAMLs and records source_hashes)
#   3. dispatches the agent via dispatch_agent() with RetryPolicy(max_attempts=3)
#   4. validates the out-bundle against the agent's pydantic schema
#   5. opens any required gate via set_pending() and waits for resolve_decision()
#   6. writes any artifact via _write_artifact()
#   7. atomically commits via _commit_stage(), which runs under
#      _deferred_sigint() and calls validate_chain() before emitting
#      stage.committed
```

The four supporting methods on `OrchestratorStore` that Claude routes through:

- `set_pending(kind: PendingDecisionKind, prompt_to_user: str, options: list[str], metadata: dict)` — opens a user-facing gate; writes `state.yaml.pending_decision` and emits `gate.opened`.
- `resolve_decision(choice: str, user_input: str | None = None, rationale: str | None = None)` — closes the in-flight gate; emits `gate.resolved`; clears `pending_decision`.
- `override(reason: str, reason_code: str)` — used for SRM overrides at Stage 5 and brief-contradiction `o` choices at Stage 3b. Carries a `SrmOverrideReasonCode` or free-text rationale.
- `dispatch_agent(agent_name: str, purpose: str | None = None)` — dispatches an agent against its assembled bundle; emits `agent.dispatched` and `agent.completed`. Called from inside `advance`; rarely called directly.

The `_commit_stage` critical section runs under `_deferred_sigint()`: if SIGINT arrives mid-commit the on-disk writes complete, `stage.committed` emits, the file lock releases, and then `KeyboardInterrupt` is raised at block exit. There is no "half-committed" state. The `_write_artifact` method writes a pydantic model to a stage-specific path under atomic-rename semantics.

If `validate_chain` returns `ok=False` mid-commit, `_commit_stage` rolls back `state.yaml` from the `.bak` backup, emits `gate.blocked(reason="chain_validation_failed")`, and refuses to commit. The user-facing recovery is `agentxp audit <exp_id> --diff`.

### Per-stage gate-firing shapes

The `set_pending` / `resolve_decision` pair is the only way to open and close a user gate, but the payload differs by stage. The shapes below are the canonical patterns Claude routes through; deviation from these breaks the audit chain validator.

Stages 0.5 and 0.75 fire one gate per drafted entity or metric. The `kind` is `confirm_semantic_model` or `confirm_metric` respectively; the `options` list carries the proposed names plus an `"edit"` and `"reject"` choice; the `metadata` carries the proposed YAML body so the audit replay can reconstruct the version the user saw. On resolution, the project-level file at `{project}/semantic_models/<entity>.yaml` (or `{project}/metrics/<name>.yaml`) is written under the shared/exclusive lock on `.project.lock`, and `state.yaml.semantic_models_refs` (or `.metrics_refs`) is updated. Stage 0.5 has a precondition: it fires only if the project has no `semantic_models/` entry for this source. Stage 0.75 likewise.

Stage 3 fires `confirm_brief` after two agents run in sequence: `designer.drafter` emits the brief, then `consistency_judge` grades it against the hypothesis. If the judge flags a contradiction, the orchestrator routes into Stage 3b instead of opening `confirm_brief` directly. Stage 3b opens `brief_contradiction` with `options=["r", "e", "o"]` and `metadata.judge_report` carrying the contradiction description. On `r`, the orchestrator rolls back to the prior `decisions/02-hypothesis.yaml` and re-enters Stage 3 with a fresh `designer.drafter` dispatch. On `e`, it dispatches `designer.editor` against the brief with the contradiction text in the context. On `o`, the user supplies a free-text rationale via `override(reason=..., reason_code="manual_continuation")`, which is recorded in `decisions/03b-contradiction.yaml`, and the brief is accepted as-is.

Stage 4 fires three gates in sequence: `confirm_data_plan` (top-level binding of brief metrics to fact sources), then `confirm_cohort` once per cohort (each window has its own gate), then `confirm_assignment` for the assignment table. The DAG transition `null→DESIGNING` rides on the Stage 3 `stage.committed`; the `DESIGNING→POWERED` transition rides on the Stage 4 `stage.committed.metadata.dag_transition: {from: "DESIGNING", to: "POWERED"}`.

Stage 5 runs the SQL safety pipeline. `sql_query_writer` proposes SRM queries; each query fires `query.proposed` with `query_id` (a ULID) and `raw_hash` + `ast_hash`. The pipeline then runs five safety layers — `sqlglot` parse, read-only check, cross-adapter consistency check, semantic-model deny-list, resource-bounds check — implemented in `agentxp/sql/safety.py`. If any layer fails, the query routes to `sql_corrector` for up to three correction attempts. If all layers pass, the orchestrator opens a `sql_review` gate (`GateKind`, not `PendingDecisionKind` — this gate fires within a single user turn and does not persist to `state.yaml.pending_decision`). The user picks `"accepted"`, `"edited"`, or `"rejected"`; on `"edited"` an `edit_override` gate fires for the modified SQL. On acceptance, the query executes against the warehouse adapter, `query.executed` fires, and the result lands at `queries/results/<hash>.parquet`. The `monitor` agent then runs `srm_check` against the result with `threshold=0.0005`. If χ² returns WARNING or BLOCK, the orchestrator opens a `srm_override` gate with `options=["override:known_imbalance", "override:manual_continuation", "override:investigation_complete", "halt"]`; the `SrmOverrideReasonCode` enum constrains the override codes.

Stage 6 runs the analyzer over the same SQL safety pipeline. Every analysis query fires `confirm_query` per the same shape as Stage 5. The `analyzer` agent's bundle carries `purpose="metric_compute"`, which the resource-bounds matrix in `agentxp/sql/schema.py` consumes to set per-purpose limits. Every stats call returns a `computation_trace`; the trace is preserved verbatim into `analyses/<ts>.json` and the audit replay walks it.

Stage 7 has no user gate. The `interpreter` agent loads its bundle (latest analysis, brief decision rules), runs the eight-step decision tree in `agentxp/interpret/tree.py`, and emits `interpretation.json` with `verdict` (one of eight `Verdict` values) and `step_fired` (one of `Literal[1, 2, 3, 4, 5, 6, 7, 8]`) recording which step of the tree produced the verdict. The confidence label is computed by `agentxp/interpret/confidence.py::map_confidence` against the 90/95% CI bounds. The interpreter's prose is single-pass voice-audited by `agentxp/render/voice_audit.py` before commit.

Stage 8 fires `confirm_readout` once. The `readout` agent renders `report.md` from `report.json` using the verdict-first template at `templates/experiment-report.md`. Every claim in `report.md` carries an `AuditPaths` block pointing at a `decisions/*.yaml`, an `analyses/*.json`, a `queries/<ulid>.yaml`, or a `bundles/*.yaml`. The voice audit runs once over the rendered markdown; if it flags a banned phrase the commit aborts and the readout re-runs with a corrective preamble.

---

## 8. CLI surface

The Python CLI binary is `agentxp`. Its source lives under `agentxp/cli/`. Each subcommand maps to a user intent and writes a specific artifact.

| User intent | CLI command | Source | What it writes |
|-------------|------------|--------|----------------|
| Inspect a dataset (Stage 0 only) | `agentxp profile <path>` | `agentxp/cli/profile.py` | `bundles/profiler.out.yaml` |
| Replay the timeline | `agentxp audit <exp_id>` | `agentxp/cli/audit.py` | (stdout text) |
| Diff two experiments | `agentxp audit <exp_id> --diff <other_exp_id>` | same | (stdout diff) |
| Render audit as HTML | `agentxp audit <exp_id> --html` | `agentxp/cli/audit_html.py` | (stdout HTML) |
| Show experiments in the project | `agentxp list` (`--status`, `--since`, `--json`) | `agentxp/cli/list.py` | (stdout table or JSON) |
| Re-enter an interrupted experiment | `agentxp resume <exp_id>` | `agentxp/cli/resume.py` | classifies into one of 8 cases (§9) |
| Release a stale `.state.lock` | `agentxp unlock <exp_id>` | `agentxp/cli/unlock.py` | removes lock if holder PID is dead |
| Walk the full eleven stages | `agentxp experiment` | `agentxp/cli/experiment.py` | placeholder; prints "talk to Claude" and exits |

The `experiment` CLI is intentionally a placeholder. The actual orchestration runs through the `/experiment` slash command, which dispatches the conversational walk via `OrchestratorStore.advance`. The placeholder exists so users who type `agentxp experiment` from a shell get a clear message about where the workflow lives.

The `profile`, `audit`, `list`, `resume`, and `unlock` commands are real and load-bearing. Claude routes natural-language intents to them via the table above.

---

## 9. Failure-mode menu

The following table condenses `OPENXP_V01_PLAN.md` §10.5. Every failure mode is wired to one canonical event + subtype; recovery routes through `/resume` unless otherwise noted.

| Trigger | Detection site | Audit event | Recovery |
|---------|---------------|-------------|----------|
| Anthropic 5xx, 429, timeout, empty body | `dispatch_agent` | `agent.completed` with `metadata.subtype="retry"` then either success (`subtype="transient_5xx"`) or `subtype="failed_after_retries"` | `RetryPolicy(max_attempts=3, backoff_base_s=1.0, backoff_max_s=16.0, max_wall_clock_s=60.0)`; on exhaustion, gate r/a/s — retry, abort stage, or save-and-resume |
| SIGINT mid `_commit_stage` | `_deferred_sigint()` context manager | `stage.committed` then `gate.blocked(reason="user_interrupt")` if SIGINT arrived inside; nothing emitted if outside | `agentxp resume <exp_id>` — Case 3 (RESUME_AT_MID_COMMIT) classifies and re-enters |
| ENOSPC (< 100MB free) | `_check_disk_space()` pre-flight in `_commit_stage` | `gate.blocked(reason="disk_full", metadata.subtype="disk_full", metadata.free_bytes, metadata.required_bytes=104857600)` | free disk space; `agentxp resume <exp_id>` re-runs pre-flight |
| Malformed YAML from agent | `dispatch_agent` after `yaml.safe_load` + pydantic | `agent.completed` with `metadata.subtype="retry"`, then on exhaustion `subtype="failed_after_retries"` | retried under same `RetryPolicy`; corrective preamble prepended; r/a/s on exhaustion |
| Warehouse credentials expired | adapter `is_auth_error()` predicate in `agentxp/sql/dispatch.py` | `query.failed(metadata.subtype="auth_expired", metadata.profile_name=<x>)` then `gate.blocked(reason="auth_expired")` | run `agentxp connect <profile>` in a separate terminal, then `agentxp resume <exp_id>` |
| `conversation.jsonl` exceeds 50MB | `ConversationStore.append()` pre-write check | warn at 50MB; at 100MB cap, rotate via `stage.committed(metadata.subtype="log_rotation", metadata.rotated_to="conversation.{N}.jsonl.gz")` | transparent — orchestrator never reads rotated files during normal stage execution |
| Agent response > 50KB | `dispatch_agent` length check before parsing | `agent.completed(metadata.subtype="oversize_response", metadata.size_bytes=<N>)` | same `RetryPolicy` and r/a/s as malformed YAML |
| `validate_chain` violation in `_commit_stage` | `agentxp/audit/chain.py::validate_chain` | `gate.blocked(reason="chain_validation_failed", metadata.details={violations: [...]}, metadata.ms=<runtime>)`; `state.yaml` rolled back from `.bak` | unsupported in v0.1; user runs `agentxp audit <exp_id> --diff` and files a bug |
| Project YAML edited between bundle assemblies | resume-time `source_hashes` comparison | `gate.opened(kind="referenced_artifact_changed")` | user accepts the new version (re-assembles) or reverts the project YAML |

The bundle snapshot policy in §10.5.9 is not a failure mode but the preventive policy that eliminates a class of would-be failures. The mechanics are in §6.

### Cross-references between failure modes and resume cases

Each failure mode in the table above terminates by writing some combination of `state.yaml.pending_decision`, a `gate.blocked` event, and an artifact rollback. The resume CLI in `agentxp/cli/resume.py` reads those rows back and classifies the experiment's position. The mapping is direct:

- 5xx exhaustion → Case 7 (`RESUME_AT_GATE_BLOCKED`). The user picks `r` (retry with a fresh `RetryPolicy` budget), `a` (abort the stage, roll back to the prior committed stage), or `s` (save; the experiment stays at pre-dispatch and a later `agentxp resume` re-enters at the same point).
- SIGINT mid `_commit_stage` → Case 3 (`RESUME_AT_MID_COMMIT`). The classifier reads the last two events; if `stage.committed` is present the commit landed and the resume continues from the next stage; if not, the resume re-enters at the prior committed stage.
- `auth_expired` → Case 7 with `subtype="auth_expired"`. The user runs `agentxp connect <profile>` in a separate terminal, then `agentxp resume`; the resume retries the specific `QueryArtifact` once with fresh credentials.
- `disk_full` → Case 7 with `subtype="disk_full"`. The pre-flight check re-runs on resume; if disk space is now sufficient the commit proceeds.
- `chain_validation_failed` → Case 8 (`RESUME_AT_UNRECOVERABLE`). Manual recovery is unsupported in v0.1; the user files a bug.
- `referenced_artifact_changed` → Case 7 with a project-level YAML SHA mismatch. The user accepts the new version (re-assembles the bundle) or reverts the project YAML.

The `r`, `a`, `s` choices at the retry-exhaustion gate map to `resolve_decision(choice="r")`, `resolve_decision(choice="a")`, and `gate.blocked(reason="user_save")` respectively. The `s` path does not emit `gate.resolved`; the next resume reads the still-open `pending_decision` and re-presents the same gate.

---

## 10. Closed-set appendix

Every closed set below is reproduced verbatim from the Python source. Use only these values; do not improvise.

### 10.1 Stage — 12 values

Source: `agentxp/schemas/state.py` class `Stage`.

```
data_loaded              # Stage 0
semantic_models_drafted  # Stage 0.5
metrics_bootstrapped     # Stage 0.75
intent_captured          # Stage 1
hypothesis_drafted       # Stage 2
brief_drafted            # Stage 3
brief_contradicted       # Stage 3b substate
data_plan_confirmed      # Stage 4
monitor                  # Stage 5
analyze                  # Stage 6
interpret                # Stage 7
readout                  # Stage 8
```

### 10.2 PendingDecisionKind — 14 values (1 reserved)

Source: `agentxp/schemas/state.py` class `PendingDecisionKind`.

```
confirm_semantic_model        # Stage 0.5 → 0.75
confirm_metric                # Stage 0.75 → 1
confirm_hypothesis            # RESERVED in v0.1 — MUST NOT be emitted; folded into confirm_brief
confirm_brief                 # Stage 3 → 4
confirm_data_plan             # Stage 4 top-level
confirm_cohort                # Stage 4 cohort sub-gate
confirm_assignment            # Stage 4 assignment sub-gate
confirm_query                 # Stage 5 + Stage 6 per-query
confirm_readout               # Stage 8
brief_contradiction           # Stage 3b r/e/o flow
srm_override                  # Stage 5 χ² yellow halt
cross_adapter_resolution      # any SQL stage
mixed_timestamp_formats       # data-quality gate
referenced_artifact_changed   # resume-time source-hash gate
```

The pydantic validator on `PendingDecision.kind` raises `ValueError` if `confirm_hypothesis` is set — the orchestrator must not emit it.

### 10.3 GateKind — 16 values

Source: `agentxp/schemas/state.py` `GateKind = Literal[...]`. Documented superset of `PendingDecisionKind`: the 14 PendingDecisionKind values plus two within-turn UX gates.

```
# 14 PendingDecisionKind values mirrored as strings (see §10.2)
confirm_semantic_model
confirm_metric
confirm_hypothesis
confirm_brief
confirm_data_plan
confirm_cohort
confirm_assignment
confirm_query
confirm_readout
brief_contradiction
srm_override
cross_adapter_resolution
mixed_timestamp_formats
referenced_artifact_changed

# 2 within-turn UX gates
sql_review       # fires after sql_query_writer emits SQL; user reviews
edit_override    # fires when user edits a SQL query at sql_review
```

### 10.4 EventName — 13 values (2 reserved for v0.2)

Source: `agentxp/audit/events.py` class `EventName`.

```
stage.entered
stage.committed
gate.opened
gate.resolved
gate.blocked
agent.dispatched
agent.completed
query.proposed
query.validated
query.executed
query.failed
hook.invoked    # RESERVED v0.1 — emitted starting v0.2 per §22.5
hook.failed     # RESERVED v0.1 — emitted starting v0.2 per §22.5
```

The two reserved values exist in the enum so v0.1 readers continue to parse v0.2 logs without a `schema_version` bump. v0.1 code must not emit them.

### 10.5 Verdict — 8 values

Source: `agentxp/schemas/report.py` class `Verdict`.

```
INVALID-SRM
LEARN-UNDERPOWERED
NO-SHIP-GUARDRAIL
NO-SHIP-PRIMARY
SHIP
ITERATE-WEAK
ITERATE-NOVELTY
LEARN
```

### 10.6 ConfidenceLabel — 7 values

Source: `agentxp/interpret/confidence.py` `ConfidenceLabel = Literal[...]`. Decision rule and orientation logic are in the same module.

```
highly likely positive
very likely positive
leaning positive
inconclusive
leaning negative
very likely negative
highly likely negative
```

### 10.7 SrmOverrideReasonCode — 3 values

Source: `agentxp/schemas/state.py` class `SrmOverrideReasonCode`.

```
known_imbalance          # external cause acknowledged
manual_continuation      # proceed without resolving
investigation_complete   # investigated; safe to continue
```

### 10.8 Stage3bChoice — 3 values

Source: `agentxp/schemas/state.py` `Stage3bChoice = Literal["r", "e", "o"]`.

```
r   # revert (drop the contradicting edit)
e   # edit (re-open the brief drafter)
o   # override (proceed with rationale)
```

---

## 11. File layout

### Per-experiment paths

Under `experiments/<exp_id>/`:

```
experiments/exp_001/
├── state.yaml              # orchestrator-owned, v3 schema; chmod 600
├── data_plan.yaml          # DataPlanV2 with status field
├── experiment.yaml         # v2 ExperimentConfig (written when Stage 3 commits)
├── conversation.jsonl      # append-only canonical conversation log; chmod 600; 100MB cap
├── log.jsonl               # append-only canonical audit log (9-field receipts); chmod 600
├── bundles/
│   ├── <agent>.ctx.yaml    # last invocation input — conversation_ref + purpose + COPIED project YAMLs + source_hashes
│   └── <agent>.out.yaml    # last invocation output
├── queries/
│   ├── <ulid>.yaml         # QueryArtifact for every SQL attempt
│   └── results/
│       └── <hash>.parquet  # result sidecar
├── decisions/
│   ├── 02-hypothesis.yaml
│   ├── 03-brief.yaml
│   ├── 03b-contradiction.yaml  # only if 3b substate fired
│   └── ...                     # one per committed user gate
├── analyses/
│   └── <ts>.json
├── interpretation.json
├── report.md
├── report.json
└── .state.lock             # filelock; carries PID + ISO start time
```

### Project-level paths

Under the project root:

```
{project}/
├── semantic_models/<entity>.yaml
├── fact_sources/<name>.yaml
├── metrics/<name>.yaml
├── assignments/<name>.yaml
└── .agentxp/
    ├── credentials/<adapter>/<profile>.yaml  # chmod 600
    ├── cache/validated_queries/              # tracked in git; SQL comments stripped
    ├── config.yaml                           # incl. pruning policy
    └── .project.lock                         # shared/exclusive coordination for project YAMLs
```

The semantic models, fact sources, metrics, and assignments are deliberately project-level (not per-experiment) so multiple experiments share a single canonical definition of "user," "session," "revenue." Stages 0.5 and 0.75 write here only when the project has no prior file for the entity or metric.

---

## 12. Stats whitelist

Every statistical routine in `agentxp.stats.*` is deterministic Python, not an LLM call. Stats functions are imported by the orchestrator and used only inside the two agents whose work is statistical interpretation. No other agent calls a stats function.

### Allowed stats calls per agent

| Agent | Stage | Allowed calls (module → function) |
|-------|-------|-----------------------------------|
| `monitor` | 5 | `agentxp.stats.srm.srm_check`; `agentxp.stats.guardrails.denominator_srm` |
| `analyzer` | 6 | `agentxp.stats.ab_tests.welch_test`; `agentxp.stats.ab_tests.proportion_test`; `agentxp.stats.ab_tests.ratio_metric_test`; `agentxp.stats.guardrails.guardrail_test`; `agentxp.stats.effect_size.cohens_d`; `agentxp.stats.effect_size_extras.cohens_h`; `agentxp.stats.effect_size.relative_lift`; `agentxp.stats.power.detectable_effect`; `agentxp.stats.corrections.adjust_pvalues`; `agentxp.stats.ab_tests.winsorize`; `agentxp.stats.guardrails.compute_late_ratio` |

All other agents — `profiler`, `semantic_modeler`, `metric_drafter`, `designer.elicitor`, `designer.drafter`, `designer.editor`, `consistency_judge`, `sql_query_writer`, `sql_corrector`, `interpreter`, `readout` — never call a stats function. They reason over the outputs that `monitor` and `analyzer` produced. The interpreter at Stage 7 consumes the `MetricResult` rows from `analyses/<ts>.json` and dispatches the eight-step decision tree in `agentxp/interpret/tree.py`; it does not recompute the underlying statistics.

### Function reference for the two allowed agents

All functions return a dict (or pydantic model) with a `computation_trace` field that records the inputs, intermediate quantities, and the test used. The trace is on by default; do not disable it. Audit replay walks the trace.

`monitor` calls:

| Function | Signature | Returns | Use |
|----------|-----------|---------|-----|
| `srm_check` | `(observed_counts, expected_ratios=None, threshold=0.0005)` | `SRMResult` with `verdict`: PASS/WARNING/BLOCK | First check at Stage 5. Threshold is `0.0005` per the orchestrator default, not the library default of `0.01` |
| `denominator_srm` | `(num_c, den_c, num_t, den_t, expected_ratio=1.0, threshold=0.05)` | dict | Sanity-check ratio-metric denominators before any ratio test |

`analyzer` calls:

| Function | Signature | Returns | Use |
|----------|-----------|---------|-----|
| `welch_test` | `(control, treatment, alpha=0.05)` | `TestResult` | Continuous metrics (revenue, duration) |
| `proportion_test` | `(c_success, c_n, t_success, t_n, alpha=0.05)` | `TestResult` | Binary metrics (converted, clicked) |
| `ratio_metric_test` | `(num_c, den_c, num_t, den_t, alpha=0.05)` | `TestResult` | Ratio metrics; delta-method variance |
| `guardrail_test` | `(control, treatment, metric_type, nim_relative=0.02, alpha=0.05, invert=False)` | dict with `verdict`: PASS/WARNING/BLOCK | One-sided non-inferiority test for guardrail metrics |
| `cohens_d` | `(control, treatment)` | `EffectSizeResult` with `magnitude` | Standardized effect size for continuous metrics |
| `cohens_h` | `(p_control, p_treatment)` | dict | Cohen's h for proportions (arcsine transform) |
| `relative_lift` | `(control_mean, treatment_mean)` | `LiftResult` | Percentage change |
| `detectable_effect` | `(n_per_group, baseline_rate=None, baseline_std=None, alpha=0.05, power=0.80)` | `MDEResult` | Post-hoc MDE check after underpowered null |
| `adjust_pvalues` | `(pvalues, method="holm", alpha=0.05)` | `CorrectionResult` | Holm-Bonferroni for pre-registered segments |
| `winsorize` | `(series, lower=0.01, upper=0.99)` | `pd.Series` | Pre-test cleanup on heavy-tailed continuous metrics |
| `compute_late_ratio` | (per signature in `agentxp/stats/guardrails.py`) | dict | Late-arriving-data ratio for novelty/late-ratio diagnostics |

When the analyzer's bundle has `purpose="metric_compute"`, the resource-bounds matrix applies the per-purpose limits in `agentxp/sql/schema.py`. The `analyses/<ts>.json` written at Stage 6 includes the `computation_trace` for every metric row.

---

## 13. Example first-turn prompts

Five examples that land on five different starting stages. Each shows how Claude routes plain English to the canonical slash command.

**"I have data at ~/data/checkout.parquet and want to look at it before designing a test."** → Stage 0 only. Route to `/profile ~/data/checkout.parquet`. The profile skill shells out to `agentxp profile`, dispatches the `profiler` agent for semantic interpretation, surfaces HG-D4 heuristic flags (mixed-timestamp columns, null-rate-on-identifier), and returns the receipt `wrote: bundles/profiler.out.yaml`. No experiment is scaffolded; no `state.yaml` is written.

**"I want to test if the new checkout button improves completion rate. My data is at ~/data/checkout.parquet."** → Stage 0 + Stage 1. Route to `/experiment --data ~/data/checkout.parquet`. The eleven-stage walk begins: profiler runs, semantic models are confirmed (or skipped if the project already has them), metrics are bootstrapped (likewise), and `designer.elicitor` captures the intent at Stage 1 with the user prose appended to `conversation.jsonl`.

**"I already have a brief at briefs/exp_001.yaml; analyze the data."** → Stage 5 onward. Route to `/experiment --from-brief briefs/exp_001.yaml`. The orchestrator scaffolds `state.yaml` with `current_stage=data_plan_confirmed` (assuming the brief is complete and the data plan has been bound), then drives the SQL safety pipeline at Stage 5: `sql_query_writer` proposes SRM queries, the user confirms via `confirm_query`, the queries execute, `monitor` runs the χ² check at threshold `0.0005`, and the walk continues through analysis, interpretation, readout.

**"What's the status of exp_007?"** → Route to `/audit exp_007` (timeline) if the user wants the history, or `/list --status` if they want a one-line summary across all experiments. The audit skill classifies the question — "status" maps to the default text timeline, "diff" maps to `--diff`, "html" or "share" maps to `--html`.

**"I'm stuck — what's the next step?"** → Route to `/resume`. If only one experiment is in progress, `/resume <exp_id>` directly. If multiple, list them first (per §3) and ask which. The resume CLI classifies the position into one of eight cases — clean end, pending decision, mid-commit SIGINT, mid-dispatch, mid-query, Stage 3b, gate-blocked, unrecoverable — and Claude presents the case-specific dialog (re-render the gate, ask permission to retry the dispatch, check the failure precondition, or surface the unrecoverable bug-report path for Case 8).

---

## 14. Voice and register

Every user-facing surface — readout prose, gate prompts, audit annotations, conversational replies — sits in an academic register. Sober and clear, with subordinate clauses doing the work that bullet lists and adjective stacks do in marketing copy. Anglo-Saxon vocabulary by default. The voice audit at `agentxp/render/voice_audit.py` is a single-pass banned-phrase grep; it runs on the interpreter and readout outputs before commit and on every CLAUDE-authored response by convention.

The banned phrase list includes "co-pilot," "colleague," "powerful," "robust," "seamless," "cutting-edge," "Let me walk you through," "Before we begin," "Great question," and "Excellent observation." These are flags for a register the system rejects; their presence implies the writer is selling the result rather than reporting it. The readout's job is to report the result, which is why the verdict-first template at `templates/experiment-report.md` opens with the verdict and the `step_fired` rationale and only then surfaces diagnostics.

Two further rules govern the conversational surface. First, never manufacture certainty the analysis does not support: when a metric's `ConfidenceLabel` is `inconclusive` or `leaning positive`, the readout says so plainly; it does not promote the result to `very likely positive` by adjective choice. Second, every claim must trace to an audit-path block; the `AuditPaths` model in `agentxp/schemas/report.py` enforces this at the schema level, but the conversational reply should observe the same discipline — when Claude says "the SRM check passed at threshold 0.0005," the next sentence (or the receipt at the end of the response) should cite `analyses/<ts>.json#srm` or the corresponding `query.executed` row.
