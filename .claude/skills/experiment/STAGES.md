# STAGES.md — per-stage specs for the AgentXP eleven-stage journey

This file is the spec the `/experiment` skill's orchestration loop reads on every iteration. Eleven sections (plus the Stage 3b substate inside Section 6) cover the journey from `data_loaded` through `readout`. Each section names the trigger that fires the stage, the precondition to check, the agent to dispatch, the inputs that go into the agent's ctx-bundle, the outputs the agent writes to its out-bundle, the user-facing gate (if any), the artifact paths the stage commits, the recipe `_commit_stage` runs, and the failure modes the stage may surface.

Closed-set callouts throughout name the source of truth in Python. `Stage` values come from `agentxp.schemas.state::Stage`; `PendingDecisionKind` values from `agentxp.schemas.state::PendingDecisionKind`; `EventName` values from `agentxp.audit.events::EventName`; `Verdict` values from `agentxp.interpret.tree::Verdict`; `ConfidenceLabel` values from `agentxp.interpret.confidence::ConfidenceLabel`.

**Voice calibration before dispatch.** Each agent has a sample dialog at `agents/fixtures/voice_samples/<agent>_sample.md`. Before composing the user-facing summary for any dispatched agent, read that agent's sample for tone calibration. This applies to every sampled agent named in the per-stage sections below; it is stated here once rather than repeated per stage.

---

## Section 1 — Stage 0 (`data_loaded`)

**Trigger.** The user invoked `/experiment --data PATH` (DATA_ONLY entry) or invoked `/experiment` with a brief that names a data source (BRIEF_AND_DATA entry). In either case the orchestrator bootstrapped a fresh `experiments/{exp_id}/` directory and `state.current_stage` was set to `Stage.DATA_LOADED` by the skill's session bootstrap.

**Precondition check.** The `source_ref` resolves through whichever adapter the wizard selected (`duckdb`, `snowflake`, or `bigquery` in v0.1; `postgres`, `mysql`, `redshift`, `databricks` defer to v0.1.1). DuckDB paths must exist and be readable; Snowflake three-level names and BigQuery `project.dataset.table` references must round-trip through `adapter.describe(source_ref)` without an `AuthExpiredError`. If the auth probe fails, route through §10.5.5 (the `auth_expired` failure mode) and exit.

**Agent.** `profiler` at `agentxp/agents/profiler.system.md`. Dispatched once. The agent receives the adapter preamble, the `source_ref`, and the result of `SUMMARIZE` (DuckDB) or its adapter equivalent — column name, type, null %, approximate distinct count, two-to-three sample values per column. Read `agents/fixtures/voice_samples/profiler_sample.md` for tone calibration before composing the summary (per the voice-calibration note above).

**Bundle assembly.** `bundles/profiler.ctx.yaml` carries `source_ref`, `adapter_kind` (`Literal["duckdb", "snowflake", "bigquery"]`), `summarize_rows` (the table the orchestrator pre-computed), `turns_so_far` (per stage), and the brief if one was provided. No project-level YAML dependencies — Stage 0 runs before `semantic_models/` exists. The profiler writes `bundles/profiler.out.yaml` as a `ProfileReport` (`agentxp.schemas.profiler::ProfileReport`).

**User input.** The profiler asks at most one question per turn, per its system prompt §6. Two heuristic flags (HG-D4) escalate to a user gate. The first is mixed timestamp formats: if any timestamp column has `mixed_format_detected=True`, the profiler pauses and the orchestrator opens a gate of kind `mixed_timestamp_formats` (one of the two data-quality `PendingDecisionKind` values). The second is null-rate-on-identifier: if a column with a name pattern suggesting unit-of-randomization (`user_id`, `account_id`, `device_id`, `session_id`) has `null_rate > 0.5`, the profiler surfaces it in the "things to check" section but does not gate — the user can either confirm or pick a different identifier in the next turn.

**Gate.** Default path: none. Escalated path: `mixed_timestamp_formats` per `PendingDecisionKind.MIXED_TIMESTAMP_FORMATS`. Options: `pick` (user picks one format, the profiler casts), `skip` (the column drops from downstream analysis). Resolution fires `gate.resolved(kind="mixed_timestamp_formats", choice=<pick|skip>)`.

**Artifact paths written.** `experiments/{exp_id}/bundles/profiler.ctx.yaml`, `experiments/{exp_id}/bundles/profiler.out.yaml`, `experiments/{exp_id}/data_plan.yaml` (partial — `source` block + `register` info only; the full plan completes at Stage 4).

**Commit recipe.** `_commit_stage(stage=Stage.DATA_LOADED, artifacts={"data_plan.yaml": partial_plan})`. Emits `EventName.STAGE_COMMITTED` with no `dag_transition` (v2 `ExperimentConfig.status` does not exist yet — it lands at Stage 3). The `agent.dispatched` and `agent.completed` event pair fires around the profiler dispatch.

**Failure modes.** Malformed profiler output triggers the `MalformedAgentOutput` retry loop in §10.5.4 (three attempts with corrective preambles, then the r/a/s gate). Oversize response triggers §10.5.7. Adapter `AuthExpiredError` routes through §10.5.5. If the user picks `skip` on `mixed_timestamp_formats`, the dropped column is recorded in `data_plan.yaml.notes` so downstream stages know it was a deliberate omission.

**Resume case.** A SIGINT mid-profiler dispatch lands the experiment in Case 4 (`RESUME_AT_AGENT_DISPATCH`) per §10.6 — `bundles/profiler.ctx.yaml` is on disk, no `bundles/profiler.out.yaml`. `agentxp resume` re-dispatches with the same bundle, emitting `agent.dispatched` with `metadata.subtype="resumed_retry"` and `metadata.attempt=N+1`.

**Referenced-artifact-changed surface.** If the source file changed between two `/experiment` sessions (the user edited the parquet file between Stage 0's profile and a downstream stage's read), the resume path detects the source hash drift and opens a gate of kind `referenced_artifact_changed` per `PendingDecisionKind.REFERENCED_ARTIFACT_CHANGED`. Options surface as r/e/o-shaped: revert to the snapshot, edit the bundle to point at the new value, or override and proceed. This gate is the data-quality counterpart to `mixed_timestamp_formats`; both are in the data-quality category of `PendingDecisionKind`.

---

## Section 2 — Stage 0.5 (`semantic_models_drafted`)

**Trigger.** Stage 0 committed. The next iteration of the orchestration loop reads `state.current_stage = Stage.SEMANTIC_MODELS_DRAFTED` and enters this section.

**Precondition check.** The project root has no `semantic_models/` directory for this source, or the directory exists but contains no YAML whose `source_ref` matches. If a matching semantic model already exists (the user has run prior experiments against this source), this stage skips: `state.current_stage` advances directly to `Stage.METRICS_BOOTSTRAPPED` without dispatching `semantic_modeler`.

**Agent.** `semantic_modeler` at `agentxp/agents/semantic_modeler.system.md`. Dispatched once. Drafts one `semantic_models/{entity}.yaml` per logical entity the profile suggests (typically one in v0.1; the agent does not invent entities the profiler did not surface).

**Bundle assembly.** `bundles/semantic_modeler.ctx.yaml` carries the `ProfileReport` from `bundles/profiler.out.yaml`, the `source_ref`, and the adapter kind. Project-level YAML dependencies: none on the input side; the agent writes new files under `semantic_models/` at commit time. The agent's output bundle (`bundles/semantic_modeler.out.yaml`) carries the drafted `SemanticModel` pydantic shape plus a one-sentence rationale per entity.

**User input.** The agent surfaces the drafted semantic model and asks for confirmation. Edits are routed through `designer.editor` (the same editor agent reused across stages); per the dot-namespace convention, `designer.editor` resolves to `agentxp/agents/designer/editor.system.md`.

**Gate.** `confirm_semantic_model` per `PendingDecisionKind.CONFIRM_SEMANTIC_MODEL`. Options: `confirm` (write the YAML, advance), `edit` (open `designer.editor`, re-draft), `skip` (leave `semantic_models/` empty and use the raw column references downstream — discouraged but supported). Resolution fires `gate.resolved(kind="confirm_semantic_model", choice=<confirm|edit|skip>)`.

**Artifact paths written.** `{project}/semantic_models/{entity}.yaml` (project-level, written under `project_write_lock` per §10.9), `experiments/{exp_id}/bundles/semantic_modeler.ctx.yaml`, `experiments/{exp_id}/bundles/semantic_modeler.out.yaml`. `state.yaml.semantic_models_refs` is updated to point at the new file(s).

**Commit recipe.** `_commit_stage(stage=Stage.SEMANTIC_MODELS_DRAFTED, artifacts={"bundles/semantic_modeler.out.yaml": out_payload})`. The project-level YAML write happens before `_commit_stage` is called (under `project_write_lock`); the chokepoint only mutates the experiment-local `state.yaml`. No `dag_transition`.

**Failure modes.** A `project_locked` failure from `project_write_lock` timeout (§10.9) fires `gate.blocked` with `reason="project_locked"` and `metadata.subtype="project_locked"`. The user retries after the holding session releases the lock; the resume case is Case 7. Malformed agent output routes through §10.5.4.

---

## Section 3 — Stage 0.75 (`metrics_bootstrapped`)

**Trigger.** Stage 0.5 committed (or skipped). `state.current_stage = Stage.METRICS_BOOTSTRAPPED`.

**Precondition check.** The project root has no `metrics/` directory, or it exists but contains no metric whose `fact_source_ref` matches a `fact_sources/*.yaml` produced at Stage 0.5. If matching metrics already exist, this stage skips and `state.current_stage` advances to `Stage.INTENT_CAPTURED`.

**Agent.** `metric_drafter` at `agentxp/agents/metric_drafter.system.md`. Dispatched once. The agent reads the semantic models and the profiler's `suggestions` block and drafts the candidate metric catalog: typically one primary candidate, one or two guardrail candidates, and a negative-control candidate when the data supports one.

**Bundle assembly.** `bundles/metric_drafter.ctx.yaml` carries the `ProfileReport.suggestions` block, the list of `SemanticModel` shapes (read from `state.yaml.semantic_models_refs` and copied into `.sources/` per §10.5.9), and the brief if one was provided. The agent's out-bundle (`bundles/metric_drafter.out.yaml`) carries one `Metric` pydantic per drafted file plus, optionally, an inline `Assignment` shape if the experiment design needs a one-off assignment binding that does not warrant a permanent `assignments/*.yaml`.

**User input.** The agent surfaces the drafted metrics catalog and asks for confirmation, the same way Stage 0.5 surfaced the semantic models. The user can confirm the entire batch, edit one metric, or drop one.

**Gate.** `confirm_metric` per `PendingDecisionKind.CONFIRM_METRIC`. Options: `confirm` (write all drafted YAMLs, advance), `edit` (route to `designer.editor` for the named metric), `drop` (the named metric is omitted). Resolution fires `gate.resolved(kind="confirm_metric", choice=<confirm|edit|drop>)`.

**Artifact paths written.** `{project}/metrics/{name}.yaml` (one per drafted metric, project-level, under `project_write_lock`), optionally `{project}/fact_sources/{name}.yaml` if the metric requires a fact source the semantic modeler did not already produce, optionally `{project}/assignments/_inline_{exp_id}.yaml` if the agent emitted an inline assignment binding. `state.yaml.metrics_refs`, `state.yaml.fact_sources_refs`, and `state.yaml.assignments_refs` are updated. Bundle paths are the usual two.

**Commit recipe.** `_commit_stage(stage=Stage.METRICS_BOOTSTRAPPED, artifacts={"bundles/metric_drafter.out.yaml": out_payload})`. Project-level writes precede the chokepoint call. No `dag_transition`.

**Failure modes.** Same `project_locked` and `MalformedAgentOutput` paths as Stage 0.5. If the inline assignment refers to a column not present in the semantic model, the validation fires before commit and the agent re-drafts (one attempt, per the §10.5.4 retry mechanics).

---

## Section 4 — Stage 1 (`intent_captured`)

**Trigger.** The user invoked `/experiment` with no `--brief PATH`. The session bootstrap asked one question — what they want to test — and the answer is the first row in `conversation.jsonl`. `state.current_stage = Stage.INTENT_CAPTURED`.

**Precondition check.** None. Stage 1 fires whenever the user is dialoguing the experiment into being. The only path that skips Stage 1 is the `--brief PATH` entry point, which jumps to Stage 5; that path is handled by the skill's bootstrap, not by this section.

**Agent.** `designer.elicitor` at `agentxp/agents/designer/elicitor.system.md`. The dot-namespace resolves the file path. The elicitor runs as a multi-turn conversation, not a single dispatch — its job is to pull intent out of the user's prose, surface the primary decision, the population in scope, and the expected direction, then advance.

**Bundle assembly.** `bundles/designer.elicitor.ctx.yaml` carries `prior_turns_compressed` (the `PriorTurnsCompressed` shape per §10.8.1 — up to fifty `CompressedTurn` rows, each with `actor`, `agent_name`, `summary` ≤300 chars, `commitments`), the brief if one was provided, and the semantic-model and metrics catalogs from Stages 0.5 and 0.75 (copied into `.sources/` per §10.5.9). The agent's out-bundle (`bundles/designer.elicitor.out.yaml`) carries the captured `intent: str` plus a flag indicating whether the conversation has enough material to advance to Stage 2.

**User input.** Multi-turn. The elicitor's job is to keep the conversation pointed at the experiment-shaped question; it does not gate. Each turn appends to `conversation.jsonl`; the `prior_turns_compressed` view in the next bundle reflects the updated dialogue.

**Gate.** None at Stage 1. The implicit "confirmation" is the elicitor's own judgment that the conversation has enough material to proceed; that judgment is encoded in the `advance_to_stage_2: bool` field on the out-bundle.

**Artifact paths written.** `experiments/{exp_id}/conversation.jsonl` (appended on every user turn — the orchestrator's `ConversationStore.append()` handles the flock + size-cap rotation per §10.5.6), `experiments/{exp_id}/bundles/designer.elicitor.ctx.yaml`, `experiments/{exp_id}/bundles/designer.elicitor.out.yaml`. `state.yaml.intent` is updated.

**Commit recipe.** `_commit_stage(stage=Stage.INTENT_CAPTURED, artifacts={"bundles/designer.elicitor.out.yaml": out_payload})`. No `dag_transition`.

**Failure modes.** None unique to this stage. The conversation can extend for many turns before the elicitor signals advance; that is normal behavior, not failure.

---

## Section 5 — Stage 2 (`hypothesis_drafted`)

**Trigger.** Stage 1 committed and the elicitor's out-bundle signaled `advance_to_stage_2 = true`. `state.current_stage = Stage.HYPOTHESIS_DRAFTED`.

**Precondition check.** None beyond the elicitor's advance signal.

**Agent.** `designer.elicitor` again at `agentxp/agents/designer/elicitor.system.md`, in its hypothesis-drafting mode. The elicitor's system prompt covers both Stage 1 (intent capture) and Stage 2 (hypothesis drafting); the difference is the ctx-bundle's `phase` field.

**Bundle assembly.** `bundles/designer.elicitor.ctx.yaml` (re-assembled with `phase="hypothesis"`) carries the captured intent, the metrics catalog (so the agent can ground the hypothesis in a real metric), the semantic models, and the updated `prior_turns_compressed`. The out-bundle carries a `Hypothesis` pydantic shape (`agentxp.schemas.state::Hypothesis`) with `primary_metric: str`, `predicted_direction: Literal["higher_is_better", "lower_is_better"]`, `predicted_magnitude_pct: float`, `guardrails: list[str]`, `segments_to_examine: list[str]`.

**User input.** The elicitor proposes the hypothesis and asks for confirmation. The confirmation is not a `confirm_hypothesis` gate in v0.1 — that `PendingDecisionKind` value (`CONFIRM_HYPOTHESIS`) is reserved-not-emitted per §6.4. The implicit confirmation folds into Stage 3's `confirm_brief` gate; the user signs off on the hypothesis when they sign off on the brief.

**Gate.** None. `PendingDecisionKind.CONFIRM_HYPOTHESIS` is in the enum for forward-compat but the orchestrator's pydantic validator (`PendingDecision._refuse_reserved`) rejects any attempt to set it in v0.1.

**Artifact paths written.** `experiments/{exp_id}/decisions/02-hypothesis.yaml` (the `Hypothesis` shape, schema_version 1), `experiments/{exp_id}/bundles/designer.elicitor.ctx.yaml` (overwritten — same agent, fresh ctx), `experiments/{exp_id}/bundles/designer.elicitor.out.yaml` (overwritten). `state.yaml.hypothesis` is updated with the structured shape.

**Commit recipe.** `_commit_stage(stage=Stage.HYPOTHESIS_DRAFTED, artifacts={"decisions/02-hypothesis.yaml": hypothesis_shape, "bundles/designer.elicitor.out.yaml": out_payload})`. No `dag_transition`.

**Failure modes.** Same `MalformedAgentOutput` retry as elsewhere. A hypothesis that names a `primary_metric` not present in the metrics catalog is a validation failure; the elicitor re-drafts with a corrective preamble.

---

## Section 6 — Stage 3 (`brief_drafted`) and Stage 3b (`brief_contradicted`)

**Trigger.** Stage 2 committed. `state.current_stage = Stage.BRIEF_DRAFTED`.

**Precondition check.** `state.yaml.hypothesis` is non-null. `state.yaml.semantic_models_refs` and `state.yaml.metrics_refs` both non-empty.

**Agent (chain).** Two-agent chain. First, `designer.drafter` at `agentxp/agents/designer/drafter.system.md` writes the brief (`ExperimentConfig` shape v2, `schema_version: 2`). Second, `consistency_judge` at `agentxp/agents/consistency_judge.system.md` checks the brief against the hypothesis (`decisions/02-hypothesis.yaml`) and against the semantic model. If the judge fires at confidence ≥ 0.7 (the constant in `agents/consistency_judge.system.md`), the orchestration loop transitions to the Stage 3b substate instead of opening the `confirm_brief` gate.

**Bundle assembly.** `bundles/designer.drafter.ctx.yaml` carries `prior_turns_compressed`, the hypothesis, the metrics catalog, the semantic models, and the segment turns extracted from the conversation. The out-bundle (`bundles/designer.drafter.out.yaml`) carries the `ExperimentConfig` shape. Then `bundles/consistency_judge.ctx.yaml` is assembled with the drafted brief, the hypothesis, and the semantic models; the judge's out-bundle (`bundles/consistency_judge.out.yaml`) carries `verdict: Literal["pass", "fail"]`, `confidence: float`, and on fail a `field_path: str`, `hypothesis_side: str`, `brief_side: str`, `judge_summary: str`.

**User input.** On the happy path (judge passes or fires below 0.7), the orchestrator surfaces the brief and asks for sign-off. On the contradicted path, the orchestrator transitions to Stage 3b and surfaces the r/e/o dialog (§10.8.2).

**Gate (happy path).** `confirm_brief` per `PendingDecisionKind.CONFIRM_BRIEF`. Options: `confirm` (advance to Stage 4 — this is the implicit hypothesis confirmation per §6.4), `edit` (route to `designer.editor` on a named field). Resolution fires `gate.resolved(kind="confirm_brief", choice=<confirm|edit>)`.

**Gate (contradicted path — Stage 3b).** `brief_contradiction` per `PendingDecisionKind.BRIEF_CONTRADICTION`. Options: `r` (revert), `e` (edit), `o` (override). Resolution fires `gate.resolved(kind="brief_contradiction", choice=<r|e|o>, metadata.override_reason=<text or null>)`. The choice is a `Stage3bChoice` (`Literal["r", "e", "o"]`).

**Stage 3b r/e/o resolution flow.** Per §10.8.2:

The `r` branch restores the prior brief from `state.yaml.history.prior_brief_hash`, emits `gate.resolved(choice="r")`, resets `state.current_stage` to `Stage.BRIEF_DRAFTED` (back to the main state), and the consistency judge does NOT re-fire on the restored brief (it was already passing before the contradiction-introducing edit).

The `e` branch dispatches `designer.editor` at `agentxp/agents/designer/editor.system.md` with a bundle scoped to the offending `field_path` only — not the whole brief. The editor accepts NL input or the `e <field> <value>` shortcut. On editor completion the bundle re-assembles (new `bundle_hash`) and `consistency_judge` runs again. If the contradiction persists, the gate re-opens with a fresh `action_id`; if resolved, the orchestrator advances to Stage 4.

The `o` branch accepts the brief as-drafted. The orchestrator renders the soft-prompt `"Saved with override. Any context to record? (or just enter)"` and captures the free-text response in `metadata.override_reason: str | None` (empty input → `None`). The contradiction is preserved in `decisions/03b-contradiction.yaml` for the audit trail. `agentxp audit --show <action_id>` of the `gate.resolved` row surfaces the override reason. The `override_reason` is free-text, NOT a closed enum — distinct from `SrmOverrideReasonCode` (Stage 5) and `NoShipReasonCode` (Stage 8).

**Artifact paths written (happy path).** `experiments/{exp_id}/experiment.yaml` (the `ExperimentConfig` v2 shape, status=`DESIGNING`), `experiments/{exp_id}/decisions/03-brief.yaml` (the brief decision record), the drafter and judge ctx/out bundles, `state.yaml.history.prior_brief_hash` updated for the next r/e/o gate.

**Artifact paths written (Stage 3b).** Additionally `experiments/{exp_id}/decisions/03b-contradiction.yaml` (the judge's structured report — schema_version 1).

**Commit recipe (happy path).** `_commit_stage(stage=Stage.BRIEF_DRAFTED, artifacts={"experiment.yaml": brief_shape, "decisions/03-brief.yaml": brief_decision}, dag_transition="null→DESIGNING")`. The `dag_transition` metadata rides on `stage.committed`; there is no separate event for DAG state changes.

**Commit recipe (Stage 3b).** No commit until the user resolves the gate. The contradiction report writes immediately; `state.current_stage` is set to `Stage.BRIEF_CONTRADICTED` via `set_pending` (which does not call `_commit_stage` — it only opens the gate and persists `pending_decision`). The eventual commit happens at whichever stage the r/e/o resolution lands at: `r` and `e` re-enter Stage 3 (the next commit will be `stage=Stage.BRIEF_DRAFTED`), `o` advances to Stage 4 (the next commit, after Stage 4 completes, will be `stage=Stage.DATA_PLAN_CONFIRMED` with `dag_transition="DESIGNING→POWERED"`).

**Failure modes.** `consistency_judge` malformed output → §10.5.4 retry loop. Drafter `MalformedAgentOutput` → same. If the judge's confidence is < 0.7, the soft warning surfaces inline in the brief sign-off prompt but no Stage 3b transition fires.

---

## Section 7 — Stage 4 (`data_plan_confirmed`)

**Trigger.** Stage 3 committed (or Stage 3b resolved to `o`). `state.current_stage = Stage.DATA_PLAN_CONFIRMED`.

**Precondition check.** `experiments/{exp_id}/experiment.yaml` exists with `status="DESIGNING"`. `state.yaml.assignments_refs` may be empty if no inline assignment was needed at Stage 0.75 — the drafter will produce one here if the brief requires it.

**Agent (chain).** Two agents on the happy path. `designer.drafter` completes the `data_plan.yaml` (the partial version from Stage 0 is now filled out with the brief's design parameters, the cohort window, the segment registry, and the multiplicity correction). If the brief introduces a new assignment binding the metric catalog does not cover, `metric_drafter` runs in `preview` mode to emit `assignments/_inline_{exp_id}.yaml`.

**Bundle assembly.** `bundles/designer.drafter.ctx.yaml` (re-assembled with `phase="data_plan"`) carries the brief, the semantic models, the assignment refs, and the metrics. The out-bundle carries the completed `DataPlanV2` shape (`schema_version: 2`, `status: Literal["draft", "confirmed", "executed"]` per F.GAP.13). If `metric_drafter` runs, its bundles are the same shape as Stage 0.75.

**User input.** Three sub-gates. The data plan as a whole is signed off via `confirm_data_plan`; the cohort window is signed off via `confirm_cohort`; the assignment binding is signed off via `confirm_assignment`. The three gates fire in order; each must resolve before the next opens. The data-plan agent renders the three sections so the user can review each in isolation.

**Gates (three).** `confirm_data_plan` per `PendingDecisionKind.CONFIRM_DATA_PLAN` (top-level), `confirm_cohort` per `PendingDecisionKind.CONFIRM_COHORT` (cohort sub-gate), `confirm_assignment` per `PendingDecisionKind.CONFIRM_ASSIGNMENT` (assignment sub-gate). Each fires `gate.opened` and resolves with `gate.resolved`. Edits to any one route through `designer.editor` and re-trigger the affected gate.

**Cohort timezone.** `cohorts.timezone: str` is an IANA name (e.g., `"America/Los_Angeles"`, `"UTC"`); defaults to `"UTC"` per §1.7.2 / B9. `cohorts.start` and `cohorts.end` are UTC-encoded (Z suffix); `timezone` records the user-facing interpretation. The `Cohort` pydantic validator (`agentxp.schemas.state::Cohort._validate_iana`) rejects non-IANA strings.

**Multiplicity.** `multiplicity.method: Literal["holm_bonferroni"]` (only value in v0.1), `multiplicity.alpha_family: float = 0.05`, `multiplicity.k_prereg: int` (number of pre-registered tests). The `k_secondary` field was dropped per M60.

**Artifact paths written.** `experiments/{exp_id}/data_plan.yaml` (full plan, status updates to `confirmed` after `confirm_data_plan` resolves), optionally `{project}/assignments/_inline_{exp_id}.yaml` (under `project_write_lock`), `experiments/{exp_id}/decisions/04-data-plan.yaml`, the drafter ctx/out bundles, and `metric_drafter` bundles if it ran.

**Commit recipe.** `_commit_stage(stage=Stage.DATA_PLAN_CONFIRMED, artifacts={"data_plan.yaml": full_plan, "decisions/04-data-plan.yaml": data_plan_decision}, dag_transition="DESIGNING→POWERED")`. This is the first DAG transition. `experiment.yaml.status` advances from `DESIGNING` to `POWERED`.

**Failure modes.** Cohort start in the future fires a soft warning (the experiment is power-ready but cannot run yet). Cohort end before cohort start fires hard rejection at the pydantic validator. Edit-cycle thrash on the three sub-gates (the user resolves `confirm_cohort` but then re-edits the cohort during `confirm_assignment`) re-opens the affected gate; each open is a fresh `gate.opened` row in `log.jsonl` with a new `action_id`.

---

## Section 8 — Stage 5 (`monitor`)

**Trigger.** Stage 4 committed. `state.current_stage = Stage.MONITOR`. `experiment.yaml.status = POWERED`.

**Precondition check.** The cohort window is open — `cohorts.start <= utcnow() <= cohorts.end` (or `cohorts.end is None`). The assignment binding is resolvable through the warehouse adapter. If the precondition fails, the orchestrator surfaces the gap (typically a still-future `cohorts.start`) and waits without dispatching.

**Agent (chain).** `sql_query_writer` at `agentxp/agents/sql_query_writer.system.md` proposes the SRM query (sample-ratio check on `assignments[{control, treatment}]`). The query flows through the five-layer SQL safety pipeline (`agentxp/sql/safety.py`): parse, read-only, cross-adapter, semantic, deny-list, resource. After Layer 4, `query.proposed` fires before the user-review screen renders. The user reviews (the `sql_review` gate, a within-turn UX gate that does not set `pending_decision`). On `accepted` (`query.validated`), the adapter executes and `query.executed` fires. Then `monitor` at `agentxp/agents/monitor.system.md` runs the SRM χ² test via `agentxp.stats.srm_check(observed_counts, expected_ratios, threshold=0.0005)`. The `0.0005` threshold is the orchestrator-passed value — strictly tighter than the library's `0.01` default — because the orchestrator's job is yellow-halt sensitivity, not pass/fail diagnosis.

**Bundle assembly.** `bundles/sql_query_writer.ctx.yaml` carries the data plan, the assignment binding, the semantic models, and the cohort window. `bundles/monitor.ctx.yaml` carries the executed query result, the brief, and `srm_threshold = 0.0005`. The monitor out-bundle (`bundles/monitor.out.yaml`) carries `srm_pass: bool`, `srm_pvalue: float`, `observed_counts: dict[str, int]`, `expected_ratios: dict[str, float]`, and the computation trace from `srm_check`.

**SQL corrector loop.** If the query fails (warehouse error, not safety-layer rejection), `sql_corrector` at `agentxp/agents/sql_corrector.system.md` re-drafts. Bounded loop: maximum three correction attempts per query. After three, the orchestrator surfaces `gate.blocked` with `reason="query_failed"` and routes the user to manual remediation. Each correction attempt fires `query.proposed` → `query.validated` → `query.executed`/`query.failed`.

**Gates.** `confirm_query` per `PendingDecisionKind.CONFIRM_QUERY` for the SRM query (and again for each analyzer query at Stage 6). If `srm_check` returns `srm_pass = false` and `srm_pvalue < 0.0005`, the SRM yellow-halt fires: `srm_override` per `PendingDecisionKind.SRM_OVERRIDE`. The override carries a `reason_code: SrmOverrideReasonCode` — one of `KNOWN_IMBALANCE` (`"known_imbalance"`, the user knows the external cause), `MANUAL_CONTINUATION` (`"manual_continuation"`, proceed without resolving), `INVESTIGATION_COMPLETE` (`"investigation_complete"`, investigated and safe to continue). Resolution fires `gate.resolved(kind="srm_override", choice="override", rationale=<text>, metadata.reason_code=<code>)` or `gate.blocked(reason="srm_override_declined")` if the user declines to override (the experiment pauses, the user runs `agentxp resume <exp_id>` after diagnosing).

**Artifact paths written.** `experiments/{exp_id}/queries/{ulid}.yaml` per SQL attempt (accepted, edited, rejected, blocked, or errored — no silent drops; `QueryArtifact` per §13), `experiments/{exp_id}/queries/results/{hash}.parquet` per successful execution, `experiments/{exp_id}/analyses/{ts}.json` (pre-analysis record), `experiments/{exp_id}/bundles/sql_query_writer.ctx.yaml` + `.out.yaml`, `experiments/{exp_id}/bundles/monitor.ctx.yaml` + `.out.yaml`, optionally `experiments/{exp_id}/bundles/sql_corrector.ctx.yaml` + `.out.yaml`.

**Commit recipe.** `_commit_stage(stage=Stage.MONITOR, artifacts={"analyses/{ts}.json": pre_analysis, "bundles/monitor.out.yaml": monitor_out}, dag_transition="POWERED→COLLECTING→ANALYZING")`. The double transition (POWERED → COLLECTING → ANALYZING) reflects the fact that Stage 5 is the moment the experiment shifts from "ready to run" through "data is in" to "analysis can begin"; the commit captures both transitions on the same `stage.committed` event.

**Failure modes.** SQL safety-layer rejection (the query violates `assert_read_only`, `assert_single_adapter`, the semantic model check, or the deny-list) is a hard halt: the query never executes, `sql_query_writer` re-drafts (within the three-attempt corrector budget). `AuthExpiredError` mid-execution routes through §10.5.5. `srm_override_declined` (the user picks the decline option on the SRM yellow-halt dialog) fires `gate.blocked(reason="srm_override_declined", metadata.subtype="srm_override_declined")` and the experiment pauses; the resume case is Case 7.

---

## Section 9 — Stage 6 (`analyze`)

**Trigger.** Stage 5 committed. `state.current_stage = Stage.ANALYZE`.

**Precondition check.** `bundles/monitor.out.yaml` exists with `srm_pass = true` (or `srm_pass = false` with a resolved `srm_override`). The cohort window has closed (`cohorts.end < utcnow()`) or the user has signaled early analysis (the `--from-stage analyze` flag).

**Agent (chain).** `sql_query_writer` proposes the analyzer queries: one per primary metric (Welch's t-test, proportion, ratio — depends on metric type), one per guardrail (non-inferiority), one per pre-registered segment in `state.yaml.segments.pre_registered`. Each query rides the five-layer safety pipeline and the `confirm_query` gate. Then `analyzer` at `agentxp/agents/analyzer.system.md` runs the statistics.

**Stats whitelist.** The analyzer ONLY uses functions from `agentxp.stats.*`. Imports from submodules (`from agentxp.stats.ab_tests import welch_test`) are forbidden; everything resolves through the top-level namespace (`from agentxp.stats import welch_test`). The whitelist is the full re-export at `agentxp/stats/__init__.py`. If a needed function is missing, the analyzer halts and the orchestrator surfaces the gap — it does not improvise the math.

**Computation trace.** Every `agentxp.stats.*` function returns a `computation_trace` dict by default (the D.9 audit trail). The analyzer preserves the trace in its out-bundle; downstream the interpreter validates the trace fields are present before walking the tree.

**Bundle assembly.** `bundles/sql_query_writer.ctx.yaml` (re-assembled per analyzer query) carries the brief, the data plan, the assignment binding, and the metric definition. `bundles/analyzer.ctx.yaml` carries the brief, the executed query results, the segment registry, and the multiplicity correction parameters. The analyzer's out-bundle (`bundles/analyzer.out.yaml`) carries the primary-metric result, the guardrail results, the segment results, and the `late_ratio` (computed by `agentxp.interpret.tree::compute_late_ratio()`).

**Gates.** `confirm_query` per `PendingDecisionKind.CONFIRM_QUERY` for each proposed analyzer query. The user reviews per query; resolutions are atomic. There is no analyzer-output gate at Stage 6 — the analyzer commits its numbers, the interpreter (Stage 7) is what renders the verdict.

**Artifact paths written.** `experiments/{exp_id}/queries/{ulid}.yaml` per query, `experiments/{exp_id}/queries/results/{hash}.parquet` per execution, `experiments/{exp_id}/analyses/{ts}.json` (full analysis with primary + guardrails + segments + traces), `experiments/{exp_id}/bundles/sql_query_writer.ctx.yaml` + `.out.yaml` (per query), `experiments/{exp_id}/bundles/analyzer.ctx.yaml` + `.out.yaml`.

**Commit recipe.** `_commit_stage(stage=Stage.ANALYZE, artifacts={"analyses/{ts}.json": full_analysis, "bundles/analyzer.out.yaml": analyzer_out})`. No `dag_transition` (the transition `COLLECTING → ANALYZING` rode on the Stage 5 commit).

**Cross-adapter resolution.** If the analyzer requires a join that spans adapters (e.g., the assignment binding lives in Snowflake and the events fact source lives in BigQuery), `assert_single_adapter` rejects the proposed query before it ever leaves the safety pipeline. The orchestrator opens a gate of kind `cross_adapter_resolution` per `PendingDecisionKind.CROSS_ADAPTER_RESOLUTION`. Three single-keystroke options: `l` (split the join across two queries, materialize an intermediate locally), `w` (move the data to a single warehouse — typically a re-execution of Stage 0 against a unified source), `o` (override and proceed with a hand-written cross-adapter query, signed off in the gate's `metadata.override_reason`). Resolution fires `gate.resolved(kind="cross_adapter_resolution", choice=<l|w|o>)`.

**Failure modes.** Same SQL safety and corrector loop as Stage 5. A stats function returning `NaN` or `inf` fires a malformed-output retry — the analyzer is expected to handle numeric edge cases (sample size of 0, baseline of 0) by returning a structured zero-effect result, not raw `NaN`. Min-sample-guard violations (sample sizes below the planned target) are captured in the analyzer's out-bundle but do not gate at Stage 6; the interpreter at Stage 7 reads `n_observed < n_required` as input to Step 3 of the decision tree. Holm-Bonferroni p-value adjustment runs as the last step before the analyzer commits, against `multiplicity.k_prereg` from `state.yaml`; the corrected p-values land in the out-bundle alongside the raw values so the audit trail captures both.

---

## Section 10 — Stage 7 (`interpret`)

**Trigger.** Stage 6 committed. `state.current_stage = Stage.INTERPRET`.

**Precondition check.** `bundles/analyzer.out.yaml` exists and carries the primary-metric result, the guardrail results, the segment results, and the `late_ratio` (formally defined in `agentxp/interpret/tree.py::compute_late_ratio` per M106 / F.GAP.29).

**Agent.** `interpreter` at `agentxp/agents/interpreter.system.md`. Single dispatch. The agent reads the analyzer's out-bundle, constructs a `TreeInput` (`agentxp.interpret.tree::TreeInput`), and dispatches `walk_tree(inputs)`. The tree is pure — no I/O, no LLM, no improvisation. The output is a `TreeResult` carrying `verdict: Verdict`, `step_fired: list[str]`, and `diagnostics: dict[str, Any]`.

**Bundle assembly.** `bundles/interpreter.ctx.yaml` carries the analyzer's output (primary CIs at 90% and 95%, guardrails with direction and CIs, sample sizes, MDE percent, baseline, late ratio), the brief's decision rules, and the multiplicity-corrected p-values from the analyzer.

**Verdict (closed eight-value set).** `Verdict = Literal["INVALID-SRM", "NO-SHIP-GUARDRAIL", "INCONCLUSIVE", "NO-LIFT", "DIRECTIONAL-ONLY", "LIFT-WITH-CAVEAT", "SHIP", "LEARN"]` per §1.8.17. Defined in `agentxp/interpret/tree.py`. The interpreter agent never invents a verdict; the tree's `walk_tree(inputs).verdict` is propagated verbatim. The eight-step tree's order is fixed (Step 1 SRM gate, Step 2 guardrails, Step 3 sample adequacy, Step 4 well-powered wide null, Step 5 directional-only signal, Step 6 magnitude vs MDE, Step 7 novelty / late-window, Step 8 LEARN terminal); the first step that fires terminates the walk.

**Confidence label (closed seven-value set).** `ConfidenceLabel = Literal["highly likely positive", "very likely positive", "leaning positive", "inconclusive", "leaning negative", "very likely negative", "highly likely negative"]` per §1.8.10. Defined in `agentxp.interpret.confidence`. The mapper translates the primary metric's CI structure (95% excludes 0 with p<0.01, 90% excludes 0 with p<0.05, 80% excludes 0 with p<0.20, CI straddles 0) into a label. The interpreter propagates the mapper's output verbatim.

**Step_fired list.** The tree's `step_fired` list records every step evaluated in the `"{N}: {rule} ({value})"` format. The interpreter writes this list verbatim into its out-bundle so the readout at Stage 8 can render the decision rationale.

**Voice audit.** The interpreter's output prose passes through `agentxp/render/voice_audit.py` (single-pass per D5) before commit. A banned-phrase hit halts the commit; the interpreter re-drafts with the offending phrase named in the corrective preamble.

**Gate.** None. The interpreter commits its judgment; the readout (Stage 8) is what carries the user-facing sign-off.

**Artifact paths written.** `experiments/{exp_id}/interpretation.json` (the structured `TreeResult` plus the confidence label and the interpreter's prose rationale), `experiments/{exp_id}/bundles/interpreter.ctx.yaml` + `.out.yaml`.

**Commit recipe.** `_commit_stage(stage=Stage.INTERPRET, artifacts={"interpretation.json": interpretation_payload, "bundles/interpreter.out.yaml": interpreter_out}, dag_transition="ANALYZING→INTERPRETED")`. `experiment.yaml.status` advances from `ANALYZING` to `INTERPRETED`.

**Failure modes.** Voice-audit rejection routes through a bounded re-draft loop (three attempts, then the r/a/s gate). `walk_tree` invariant violations (e.g., the analyzer emitted a `late_ratio` that fails the helper's NaN/inf guard) are surfaced before the tree walks; the analyzer re-runs the late-window slicing. A `Verdict` not in the closed set is impossible by construction (the tree's return type is the closed Literal).

---

## Section 11 — Stage 8 (`readout`)

**Trigger.** Stage 7 committed. `state.current_stage = Stage.READOUT`.

**Precondition check.** `interpretation.json` exists with a non-null `verdict` and `confidence_label`. The analyzer's out-bundle is still on disk for the readout to reference.

**Agent (prose-only).** `readout` at `agents/readout.system.md`. Single dispatch. The agent reads the interpreter's output, the analyzer's output, and the brief and writes ONLY its prose bundle (`bundles/readout.out.yaml`): `verdict_rationale`, the 1–5 `uncertainty_notes`, and the stakeholder summary. **The agent no longer writes `report.json` or any verifiable field** (chain hash, locked-brief hash, version, the verdict-tree scalars, per-arm/CI). Those are computed by the deterministic core finalizer (below) so the component being policed cannot author its own receipts.

**Bundle assembly.** `bundles/readout.ctx.yaml` carries the interpretation, the analyzer output, the brief, the data plan, and the audit paths. The agent's out-bundle (`bundles/readout.out.yaml`) is the **prose bundle** — `verdict_rationale`, `uncertainty_notes`, stakeholder summary — and nothing the finalizer must compute itself.

**Finalize (deterministic core).** After the agent commits its prose bundle and BEFORE anything reads `report.json`, the orchestrator calls `agentxp.finalize::finalize_report(exp_dir)`. It recomputes the verdict from the analyzer's committed numbers via `agentxp.interpret.tree::walk_tree` (cross-checking against — never trusting — the interpreter agent's claimed verdict, and raising `FinalizeError` on divergence), computes `chain_hash = canonical_chain_hash(exp_dir)`, `locked_brief_hash = sha256(experiment.yaml)`, and `agentxp_version`, pulls the verdict-tree scalars + per-arm/CI from the analyzer/interpreter bundles, merges the agent prose, assembles the `Report` model (`agentxp.schemas.report::Report`, schema_version 2), and writes `report.json` atomically (chmod 600). `report.md` is a deterministic render over that canonical `report.json` (the markdown adapter; W1 of the presentation layer).

**Voice audit.** Single-pass per D5. The rendered markdown passes through `agentxp/render/voice_audit.py` before commit. A banned-phrase hit halts; the readout re-drafts with the phrase named.

**Gate.** `confirm_readout` per `PendingDecisionKind.CONFIRM_READOUT`. Options: `confirm` (sign off, the experiment terminates at `Stage.READOUT`), `edit` (route to a re-draft with named changes). On a NO-SHIP verdict (`NO-SHIP-GUARDRAIL`, `DIRECTIONAL-ONLY`, `INCONCLUSIVE`, `NO-LIFT`, or `LIFT-WITH-CAVEAT` per the user's call), the confirm prompt carries an additional field — `reason_code: NoShipReasonCode` (the four-value enum at `agentxp.schemas.readout::NoShipReasonCode`: `GUARDRAIL_VIOLATION`, `DIRECTIONAL_ONLY`, `INSUFFICIENT_EVIDENCE`, `CONTRADICTORY_SEGMENTS`). On SHIP and LEARN, no reason code is required.

**Reason-code distinction.** `NoShipReasonCode` is the user's chosen NO-SHIP framing at readout sign-off. `Verdict` is the interpreter's machine-derived classification. The two enums operate at different layers: a `DIRECTIONAL-ONLY` verdict often results in the user picking the `directional_only` reason code at sign-off; the verdict is the diagnosis, the reason code is the decision. Distinct from `SrmOverrideReasonCode` (Stage 5), which is causal — what explained the imbalance.

**Artifact paths written.** `experiments/{exp_id}/report.md` (verdict-first markdown, rendered over `report.json`), `experiments/{exp_id}/report.json` (sidecar — schema_version 2, written by `finalize_report()`, NOT the agent), `experiments/{exp_id}/bundles/readout.ctx.yaml` + `.out.yaml` (the prose bundle).

**Commit recipe.** The agent prose bundle commits first; then `finalize_report(exp_dir)` writes `report.json`; then `_commit_stage(stage=Stage.READOUT, artifacts={"report.md": markdown_body, "report.json": report_payload, "bundles/readout.out.yaml": readout_out}, dag_transition="INTERPRETED→REPORTED")`. `experiment.yaml.status` advances from `INTERPRETED` to `REPORTED`. This is the terminal commit; the orchestration loop exits after `_commit_stage` returns.

**Failure modes.** Voice-audit rejection routes through the bounded re-draft loop. A `confirm_readout` resolution of `edit` re-dispatches the readout agent with the user's named changes in the ctx-bundle; the gate re-opens on the re-drafted version. A SIGINT mid-`_commit_stage` is handled by `_defer_sigint` per §10.5.2; the commit lands or rolls back atomically.

**Terminal state.** After Stage 8 commits, `state.current_stage = Stage.READOUT`, `state.pending_decision = None`, `state.stage_history[-1].stage = Stage.READOUT`. A subsequent `agentxp resume <exp_id>` classifies into Case 1 (`RESUME_AT_CLEAN_END`) and prints the no-op confirmation.

**Share tail (skippable, non-blocking).** After the terminal commit lands, the orchestrator MAY surface a soft share prompt — but only when `sys.stdin.isatty()` is true. On a non-interactive run (CI, a pipe, `--yes`), the tail is skipped silently and the run ends normally; it never blocks on stdin. The prompt is a single line whose default action is "do nothing":

```
Readout committed. Share it? (enter to skip)
```

Pressing enter (empty input) terminates the run normally — identical to not showing the tail at all. The committed `report.md` is already on disk regardless; this tail only offers an OPTIONAL re-render to another surface. In Wave 2 the only offered action is `(enter to skip)`; the share options (`g` glance to clipboard, `h` exec HTML, `p` public card) are added in W4/W5 as those adapters land. The tail NEVER re-runs the pipeline — it calls only the render path (`agentxp report <id> --format …`), which reads the committed `report.json`. This keeps presentation strictly downstream of the finalized sidecar.

**On-demand re-render (`/share-experiment <id>`).** Independent of the Stage-8 tail, `/share-experiment <id> [--format <fmt>] [--audience <aud>]` re-enters ONLY the render step against an already-committed `report.json`. It runs `distill(report) → build_provenance(report, exp_dir) → adapter` (i.e. shells out to `agentxp report <id> …`) and never re-dispatches an agent, re-queries the warehouse, or re-walks the verdict tree. It is the supported way to produce a fresh surface (a new format, an updated provenance receipt after a `validate_chain` change) without re-running the experiment. If `report.json` is absent (experiment not finalized to Stage 8) it errors the same way the `report` verb does (`no report.json — run the experiment to Stage 8 first`).

---

## Cross-references

- `SKILL.md` (this directory) — the orchestration loop that consumes these specs.
- `agentxp/schemas/state.py` — `Stage`, `PendingDecisionKind`, `GateKind`, `Stage3bChoice`, `SrmOverrideReasonCode`, `Cohort`, `Hypothesis`, `Multiplicity`.
- `agentxp/audit/events.py` — `EventName` (thirteen-value closed enum).
- `agentxp/interpret/tree.py` — `Verdict` (eight-value closed Literal), `walk_tree()`, `TreeInput`, `TreeResult`, `compute_late_ratio()`.
- `agentxp/interpret/confidence.py` — `ConfidenceLabel` (seven-value closed Literal).
- `agentxp/schemas/readout.py` — `NoShipReasonCode` (four-value enum), `Report`.
- `agentxp/orchestrator/store.py` — `_commit_stage`, `set_pending`, `resolve_decision`, `override`, `dispatch_agent`.
- `agentxp/orchestrator/bundle.py` — `BundleStore.assemble()`, `AgentBundle`.
- `agentxp/render/report.py` — `render_report()`.
- `agentxp/render/voice_audit.py` — single-pass banned-phrase audit.
- `agentxp/sql/safety.py` — five-layer safety pipeline.
- `experimentation-platform/OPENXP_V01_PLAN.md` — §3 (journey), §5 (agents), §6 (state schema), §10 (orchestrator API), §10.5 (failure modes), §10.6 (resume cases), §10.8.2 (Stage 3b r/e/o), §11 (SQL pipeline), §22 (interpreter tree), §23 (confidence framing).
